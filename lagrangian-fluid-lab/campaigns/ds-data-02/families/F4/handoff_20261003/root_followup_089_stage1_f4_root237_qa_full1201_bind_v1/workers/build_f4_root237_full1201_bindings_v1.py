#!/usr/bin/env python3
"""Build fresh089's disabled Root237 -> Root230 F4 qualification requests.

This is a metadata binder.  It consumes producer-registered GenCase and
Root237 QA receipts, hashes only JSON/XML/Python/policy files, and uses
``stat`` for the producer-owned BI4.  It never starts a process and never
opens or rehashes a scientific array.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parents[1]
FRESH087 = PACKAGE.parent / "root_followup_087_stage1_drop_gap_lattice_aligned_fallback6_source_v1"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
HANDOFF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
ROOT230 = HANDOFF / "root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT134 = HANDOFF / "root_stage1_f3_first24_eight_solver_resource_policy_134"
RESOURCE_WINDOW = HANDOFF / "root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
GENCASE_BINDING = HANDOFF / "root_stage1_f4_six_actual_native_initial_qa_235/actual-individual-gencase-binding.json"
REGISTERED_INDEX = HANDOFF / "root_stage1_f4_six_lattice_aligned_genuine_gencase_227/root-source-review-and-request-index.json"
QA_ROOT = DATA / "families/F4/F4_FALLBACK6_LATTICE_DP010_INITIAL_QA/root-stage1-f4-six-aligned-gap-actual-gen-receipt-json-alias-native-qa-237"
QA_ATTEMPT = "root-stage1-f4-six-aligned-gap-actual-gen-receipt-json-alias-native-qa-237"
ROOT235 = DATA / "families/F4/F4_FALLBACK6_LATTICE_DP010_INITIAL_QA/root-stage1-f4-six-aligned-gap-actual-native-initial-qa-235"
ROOT236 = DATA / "families/F4/F4_FALLBACK6_LATTICE_DP010_INITIAL_QA/root-stage1-f4-six-aligned-gap-native-initial-qa-actual-receipt-alias-repair-236"
ROOT235_BINDING = HANDOFF / "root_stage1_f4_six_actual_native_initial_qa_235/actual-individual-gencase-binding.json"
ROOT237_SOURCE = HANDOFF / "root_stage1_f4_six_actual_gen_receipt_json_alias_native_qa_237"
ROOT236_SOURCE = HANDOFF / "root_stage1_f4_six_native_initial_qa_actual_receipt_alias_repair_236"
QA_AUDIT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_f4_centered_reference_v1.py"
QA_LABELS = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_native_labels.py"
F2_MASS_AUDIT = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/f2_handoff_20261002_native_mass_audit.py"
SAFE_BI4_DECODER = INTEGRATION / "lagrangian-fluid-lab/scripts/f8_r008_safe_bi4_decoder_v1.py"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
ROOT230_ENTRY = ROOT230 / "launch.py"
ROOT230_HOME = ROOT230 / "root_native_home_floor_inventory_policy.py"
ROOT230_GPU = ROOT134 / "ds02_root_all_idle_gpu_policy_v2.py"
ROOT230_CONTRACT = ROOT230 / "source-policy-contract.json"
FRESH087_WORKER = FRESH087 / "workers/run_f4_fallback_native_initial_qa_v1.py"
FRESH088_REQUEST = PACKAGE.parent / "root_followup_088_stage1_individual_gencase_receipt_binding_v1/requests/root227-six-case-native-qa.request.json"

ARRAY_SUFFIXES = {".bi4", ".h5", ".vtk", ".csv"}
HEX64 = set("0123456789abcdef")
EFFECTIVE_RESERVATION_SHA = "46e62ea197862a833797556d09350126b3632b2e3b1d496d08816ee42f7abecf"
ROOT230_PROFILE = "root_live_all_idle_uuid_leased_eight_solver_v2"
ROOT230_DATASET_PROFILE = "root_home_floor_no_legacy_dataset_walk_native_v1"


def sha256(path: Path) -> str:
    if path.suffix.lower() in ARRAY_SUFFIXES:
        raise ValueError(f"source binder may not hash a scientific array: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def csha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in ARRAY_SUFFIXES:
        raise ValueError(f"array cannot be loaded as metadata: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX64


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_root230() -> dict[str, Any]:
    paths = {
        "entry": ROOT230_ENTRY,
        "home_policy": ROOT230_HOME,
        "gpu_policy": ROOT230_GPU,
        "contract": ROOT230_CONTRACT,
        "runtime": RUNTIME,
        "strict": STRICT,
        "resource_window": RESOURCE_WINDOW,
        "solver": SOLVER,
    }
    refs = {name: {"path": str(require_file(path)), "sha256": sha256(path)} for name, path in paths.items()}
    contract = load_json(ROOT230_CONTRACT)
    if contract.get("schema") != "ds02.root.native-home-floor-policy.v1":
        raise ValueError("Root230 policy contract schema drift")
    if contract.get("new_policy_sha256") != refs["home_policy"]["sha256"]:
        raise ValueError("Root230 Home-floor policy digest drift")
    if contract.get("entry_sha256") != refs["entry"]["sha256"]:
        raise ValueError("Root230 entry digest drift")
    if contract.get("runtime_file_unchanged") is not True or contract.get("source_only_no_jobs_started") is not True:
        raise ValueError("Root230 contract does not preserve runtime/source-only guards")
    gpu_text = ROOT230_GPU.read_text(encoding="utf-8")
    if "PROFILE = 'root_live_all_idle_uuid_leased_eight_solver_v2'" not in gpu_text:
        raise ValueError("Root230 eight-UUID policy profile drift")
    if "if len(active) >= 8:" not in gpu_text:
        raise ValueError("Root230 eight-solver cap is not explicit")
    return {
        "profile": ROOT230_PROFILE,
        "dataset_inventory_profile": ROOT230_DATASET_PROFILE,
        "effective_reservation_function_sha256": EFFECTIVE_RESERVATION_SHA,
        "references": refs,
        "home_free_gib_floor": 500,
        "nvme_free_gib_floor": 100,
        "nvme_peak_gib": 24,
        "solver_concurrency_cap": 8,
        "foreign_process_policy": "Root230 live UUID inventory and lease checks remain owner-side; source package does not inspect or alter processes",
    }


def endpoint_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    endpoints = plan.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 6:
        raise ValueError("fresh087 source plan must contain six endpoints")
    result = {}
    for row in endpoints:
        eid = str(row.get("endpoint_id"))
        if eid in result:
            raise ValueError(f"duplicate endpoint: {eid}")
        result[eid] = row
    return result


def verify_qa(qa_root: Path, gencase_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    receipt_path = require_file(qa_root / "execution-receipt.json")
    index_path = require_file(qa_root / "initial-native-qa-index.json")
    binding_path = require_file(qa_root / "initial-native-qa-binding.json")
    summary_path = require_file(qa_root / "producer-summary.json")
    receipt = load_json(receipt_path)
    index = load_json(index_path)
    binding = load_json(binding_path)
    summary = load_json(summary_path)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("Root237 QA execution receipt is not completed0")
    if receipt.get("request", {}).get("attempt_id") != QA_ATTEMPT:
        raise ValueError("Root237 QA attempt identity drift")
    if index.get("status") != "completed" or index.get("pass") is not True or index.get("case_count") != 6:
        raise ValueError("Root237 QA index is not a six-case pass")
    if index.get("arrays_read_by_job") is not True or index.get("raw_native_marker_arrays_observed") != []:
        raise ValueError("Root237 QA index array provenance drift")
    binding_case_rows = binding.get("cases")
    if binding.get("status") != "completed" or binding.get("pass") is not True or not isinstance(binding_case_rows, list) or len(binding_case_rows) != 6:
        raise ValueError("Root237 QA binding is not a six-case pass")
    if binding.get("independent_case_count_increment") != 0 or binding.get("root_gencase_parent_preserved") is not True:
        raise ValueError("Root237 QA credit/lineage guard drift")
    if summary.get("status") != "completed" or summary.get("case_count") != 6 or summary.get("arrays_read_by_source") is not False:
        raise ValueError("Root237 producer summary drift")
    index_cases = {str(row["endpoint_id"]): row for row in index.get("cases", [])}
    binding_cases = {str(row["endpoint_id"]): row for row in binding.get("cases", [])}
    if set(index_cases) != set(gencase_rows) or set(binding_cases) != set(gencase_rows):
        raise ValueError("Root237 QA endpoint set differs from GenCase producer set")
    rows: dict[str, dict[str, Any]] = {}
    for eid in gencase_rows:
        idx = index_cases[eid]
        bnd = binding_cases[eid]
        if idx.get("pass") is not True or bnd.get("pass") is not True:
            raise ValueError(f"{eid}: Root237 case did not pass")
        report_path = Path(str(bnd.get("path")))
        if not report_path.is_file():
            raise FileNotFoundError(report_path)
        report = load_json(report_path)
        report_sha = sha256(report_path)
        if bnd.get("report_sha256") != report_sha or idx.get("report_sha256") != report_sha:
            raise ValueError(f"{eid}: Root237 report digest mismatch")
        if report.get("pass") is not True or report.get("native_audit_returncode") != 0:
            raise ValueError(f"{eid}: native report is not pass/OS0")
        if report.get("arrays_read_by_source") is not False:
            raise ValueError(f"{eid}: source claimed array access")
        observed = report.get("raw_native_arrays_observed")
        if observed != ["Posd", "Idp"]:
            raise ValueError(f"{eid}: native audit did not record Posd/Idp")
        gen = gencase_rows[eid]
        if report.get("source_gencase_receipt_sha256") != gen["gencase_receipt_sha256"]:
            raise ValueError(f"{eid}: QA report GenCase receipt digest drift")
        if report.get("source_generated_xml_sha256") != gen["generated_xml_sha256"]:
            raise ValueError(f"{eid}: QA report XML digest drift")
        if report.get("source_generated_bi4_producer_sha256") != gen["generated_bi4_producer_sha256"]:
            raise ValueError(f"{eid}: QA report BI4 producer digest drift")
        metadata_path = require_file(qa_root / "metadata" / f"{eid}.metadata.json")
        metadata = load_json(metadata_path)
        if metadata.get("case_id") != eid or metadata.get("source_only") is not True:
            raise ValueError(f"{eid}: Root237 metadata identity/source-only drift")
        rows[eid] = {
            "report_path": str(report_path),
            "report_sha256": report_sha,
            "metadata_path": str(metadata_path),
            "metadata_sha256": sha256(metadata_path),
            "report": report,
            "index_case": idx,
            "binding_case": bnd,
        }
    return {
        "attempt_id": QA_ATTEMPT,
        "root": str(qa_root),
        "execution_receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)},
        "index": {"path": str(index_path), "sha256": sha256(index_path)},
        "binding": {"path": str(binding_path), "sha256": sha256(binding_path)},
        "producer_summary": {"path": str(summary_path), "sha256": sha256(summary_path)},
        "case_count": 6,
        "cases": rows,
        "status": "completed_pass",
        "arrays_read_by_source": False,
        "arrays_read_by_job": True,
        "claim_boundary": "Initial native input QA only; no full solver, visual, precision, Q-N, production, or independent-case credit.",
    }


def verify_gencase(binding: dict[str, Any], endpoints: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if binding.get("case_count") != 6 or binding.get("independent_case_count_increment") != 0:
        raise ValueError("Root227 producer binding count/credit drift")
    rows = binding.get("per_case_actual_gencase_receipts")
    if not isinstance(rows, list):
        raise ValueError("Root227 producer binding lacks per-case receipts")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        eid = str(row.get("endpoint_id"))
        if eid not in endpoints or eid in result:
            raise ValueError(f"unexpected or duplicate GenCase endpoint: {eid}")
        receipt_obj = row.get("gencase_receipt")
        xml_obj = row.get("generated_xml")
        bi4_obj = row.get("generated_bi4")
        if not all(isinstance(x, dict) for x in (receipt_obj, xml_obj, bi4_obj)):
            raise ValueError(f"{eid}: incomplete producer binding")
        receipt_path = require_file(Path(str(receipt_obj["path"])))
        receipt_sha = sha256(receipt_path)
        expected_receipt_sha = receipt_obj.get("producer_sha256") or receipt_obj.get("observed_sha256")
        if not valid_sha(expected_receipt_sha) or receipt_sha != expected_receipt_sha:
            raise ValueError(f"{eid}: GenCase receipt producer digest mismatch")
        receipt = load_json(receipt_path)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise ValueError(f"{eid}: GenCase receipt is not completed0")
        total = receipt.get("total_particles", row.get("total_particles"))
        fluid = receipt.get("fluid_particles", row.get("fluid_particles"))
        # The official runtime receipt records total/fluid/dimension.  The
        # producer-registered row is the authoritative fixed partition for
        # this individual GenCase output.
        fixed = receipt.get("fixed_particles", row.get("fixed_particles"))
        if not all(isinstance(x, int) and x > 0 for x in (total, fluid, fixed)) or fluid >= total:
            raise ValueError(f"{eid}: actual GenCase counts are missing/invalid")
        if receipt.get("solver_dimension_from_gencase") != 3:
            raise ValueError(f"{eid}: GenCase is not actual 3D")
        xml_path = require_file(Path(str(xml_obj["path"])))
        xml_sha = sha256(xml_path)
        if xml_sha != xml_obj.get("producer_sha256"):
            raise ValueError(f"{eid}: generated XML producer digest mismatch")
        bi4_path = require_file(Path(str(bi4_obj["path"])))
        bi4_size = bi4_path.stat().st_size
        if bi4_size <= 0 or bi4_obj.get("size_bytes_from_stat") not in (None, bi4_size):
            raise ValueError(f"{eid}: generated BI4 stat drift")
        bi4_sha = bi4_obj.get("producer_sha256")
        if not valid_sha(bi4_sha):
            raise ValueError(f"{eid}: generated BI4 lacks producer digest")
        report_path = require_file(Path(str(row["prepared_input_report"])))
        report = load_json(report_path)
        if report.get("xml_sha256") != xml_sha or report.get("bi4_sha256") != bi4_sha:
            raise ValueError(f"{eid}: prepared producer report digest drift")
        result[eid] = {
            "endpoint_id": eid,
            "gencase_receipt": str(receipt_path),
            "gencase_receipt_sha256": receipt_sha,
            "generated_xml": str(xml_path),
            "generated_xml_sha256": xml_sha,
            "generated_bi4": str(bi4_path),
            "generated_bi4_producer_sha256": bi4_sha,
            "generated_bi4_size_bytes": bi4_size,
            "prepared_input_report": str(report_path),
            "prepared_input_report_sha256": sha256(report_path),
            "total_particles": total,
            "fluid_particles": fluid,
            "fixed_particles": fixed,
            "returncode": 0,
            "solver_dimension_from_gencase": 3,
            "physical_condition_sha256": row.get("physical_condition_sha256"),
        }
    if set(result) != set(endpoints):
        raise ValueError("Root227 producer endpoint set differs from fresh087 plan")
    return result


def add_manifest_entry(entries: list[dict[str, Any]], role: str, path: Path, *, producer_sha256: str | None = None) -> None:
    if any(entry["role"] == role for entry in entries):
        raise ValueError(f"duplicate manifest role: {role}")
    if path.suffix.lower() in ARRAY_SUFFIXES:
        entries.append({
            "role": role,
            "path": str(path),
            "required": True,
            "expected_sha256": None,
            "producer_sha256": producer_sha256,
            "read_by_source": False,
            "read_policy": "stat_only_producer_digest_no_open_no_rehash",
        })
    else:
        require_file(path)
        entries.append({
            "role": role,
            "path": str(path),
            "required": True,
            "expected_sha256": sha256(path),
            "producer_sha256": None,
            "read_by_source": False,
        })


def make_manifest(eid: str, plan: dict[str, Any], gencase: dict[str, Any], qa: dict[str, Any], root230: dict[str, Any]) -> dict[str, Any]:
    endpoint = endpoint_map(plan)[eid]
    owner_path = FRESH087 / "owners" / f"{eid}.owner.json"
    metadata_path = FRESH087 / "metadata" / f"{eid}.metadata.json"
    definition_path = FRESH087 / str(endpoint["source_definition_output"])
    qa_case = qa["cases"][eid]
    entries: list[dict[str, Any]] = []
    add_manifest_entry(entries, "canonical_owner", owner_path)
    add_manifest_entry(entries, "metadata", metadata_path)
    add_manifest_entry(entries, "source_definition", definition_path)
    add_manifest_entry(entries, "source_plan", FRESH087 / "source-plan.json")
    add_manifest_entry(entries, "source_build_receipt", FRESH087 / "source-build-receipt.json")
    add_manifest_entry(entries, "registered_root_index", REGISTERED_INDEX)
    add_manifest_entry(entries, "actual_gencase_binding", GENCASE_BINDING)
    add_manifest_entry(entries, "actual_gencase_receipt", Path(gencase["gencase_receipt"]))
    add_manifest_entry(entries, "actual_prepared_input_report", Path(gencase["prepared_input_report"]))
    add_manifest_entry(entries, "generated_xml", Path(gencase["generated_xml"]), producer_sha256=gencase["generated_xml_sha256"])
    add_manifest_entry(entries, "generated_bi4", Path(gencase["generated_bi4"]), producer_sha256=gencase["generated_bi4_producer_sha256"])
    add_manifest_entry(entries, "qa_execution_receipt", Path(qa["execution_receipt"]["path"]))
    add_manifest_entry(entries, "qa_index", Path(qa["index"]["path"]))
    add_manifest_entry(entries, "qa_binding", Path(qa["binding"]["path"]))
    add_manifest_entry(entries, "qa_case_report", Path(qa_case["report_path"]))
    add_manifest_entry(entries, "qa_case_metadata", Path(qa_case["metadata_path"]))
    add_manifest_entry(entries, "source_qa_worker", FRESH087_WORKER)
    add_manifest_entry(entries, "official_audit", QA_AUDIT)
    add_manifest_entry(entries, "native_label_decoder", QA_LABELS)
    add_manifest_entry(entries, "root237_worker", ROOT237_SOURCE / "run_f4_fallback_native_initial_qa_root237.py")
    add_manifest_entry(entries, "root237_contract_repair", ROOT237_SOURCE / "source-contract-repair.json")
    add_manifest_entry(entries, "root236_worker", ROOT236_SOURCE / "run_f4_fallback_native_initial_qa_root236.py")
    add_manifest_entry(entries, "root236_child_preflight", ROOT236_SOURCE / "metadata-child-audit-preflight.json")
    add_manifest_entry(entries, "f2_mass_audit", F2_MASS_AUDIT)
    add_manifest_entry(entries, "safe_bi4_decoder", SAFE_BI4_DECODER)
    add_manifest_entry(entries, "root230_entry", ROOT230_ENTRY)
    add_manifest_entry(entries, "root230_home_policy", ROOT230_HOME)
    add_manifest_entry(entries, "root230_gpu_policy", ROOT230_GPU)
    add_manifest_entry(entries, "root230_contract", ROOT230_CONTRACT)
    add_manifest_entry(entries, "runtime", RUNTIME)
    add_manifest_entry(entries, "strict_dispatch", STRICT)
    add_manifest_entry(entries, "resource_window", RESOURCE_WINDOW)
    add_manifest_entry(entries, "solver_binary", SOLVER)
    return {
        "schema": "ds02.f4.root237-child-audit-input-manifest.v1",
        "scope_id": "root_followup_089_stage1_f4_root237_qa_full1201_bind_v1",
        "family_id": "F4",
        "case_id": eid,
        "root237_qa_attempt": QA_ATTEMPT,
        "entries": entries,
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "gencase_counts_are_actual": {
            "total": gencase["total_particles"],
            "fluid": gencase["fluid_particles"],
            "fixed": gencase["fixed_particles"],
        },
        "qa_report_pass": True,
        "qa_report_arrays_read_by_job": True,
        "qa_report_raw_arrays": ["Posd", "Idp"],
        "root230": root230,
        "claim_boundary": "Complete child input provenance for Root237 initial QA and a future Root230 native solver; this manifest grants no launch or scientific qualification.",
    }


def make_request(eid: str, endpoint: dict[str, Any], owner: dict[str, Any], metadata: dict[str, Any], gencase: dict[str, Any], qa: dict[str, Any], manifest_path: Path, evidence_path: Path, root230: dict[str, Any], plan_path: Path, build_receipt_path: Path, owner_path: Path, metadata_path: Path, definition_path: Path, gencase_binding_path: Path, registered_index_path: Path, builder_path: Path, preflight_path: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    all_entries = manifest["entries"]
    active_entries = [entry for entry in all_entries if entry["role"] not in {"generated_xml", "generated_bi4"}]
    input_files = [str(entry["path"]) for entry in active_entries] + [str(evidence_path), str(builder_path), str(preflight_path)]
    # Stable de-duplication keeps the request readable while preserving the
    # manifest's child order for reviewers.
    seen: set[str] = set()
    input_files = [x for x in input_files if not (x in seen or seen.add(x))]
    input_sha = {path: sha256(Path(path)) for path in input_files}
    prefix = Path(gencase["generated_xml"]).with_suffix("")
    attempt_id = f"root-stage1-f4-{eid.lower()}-full1201-native-qualification-root230-089"
    qa_case = qa["cases"][eid]
    qa_refs = {
        "provider_attempt_id": QA_ATTEMPT,
        "status": "completed_pass",
        "execution_receipt": qa["execution_receipt"]["path"],
        "execution_receipt_sha256": qa["execution_receipt"]["sha256"],
        "index": qa["index"]["path"],
        "index_sha256": qa["index"]["sha256"],
        "binding": qa["binding"]["path"],
        "binding_sha256": qa["binding"]["sha256"],
        "case_report": qa_case["report_path"],
        "case_report_sha256": qa_case["report_sha256"],
        "case_metadata": qa_case["metadata_path"],
        "case_metadata_sha256": qa_case["metadata_sha256"],
        "pass": True,
        "raw_native_arrays": ["Posd", "Idp"],
        "raw_native_marker_arrays": [],
        "independent_case_count_increment": 0,
    }
    return {
        "schema": "ds02.runner-request.v2",
        "attempt_id": attempt_id,
        "case_id": eid,
        "family_id": "F4",
        "scope_id": "root_followup_089_stage1_f4_root237_qa_full1201_bind_v1",
        "kind": "qualification",
        "cpu_task_kind": "native_solver",
        "command": [
            str(SOLVER),
            str(prefix),
            "{attempt_root}/solver_output",
            "-tmax:1.2",
            "-tout:0.001",
        ],
        "cwd": str(prefix.parent),
        "max_wall_seconds": 14400,
        "cpu_threads": 2,
        "estimated_peak_gpu_mib": 8192,
        "estimated_storage_bytes": 214748364800,
        "launch": False,
        "launch_allowed": False,
        "launch_owner": "root",
        "execution_allowed": False,
        "source_only": True,
        "status": "source_only_disabled",
        "root_review_required": True,
        "disabled_reason": "Root may enable only after reviewing actual Root237 six-case native initial QA and the complete child-input manifest; this request is source-only and carries no visual, precision, Q-N, production, or independent-case approval.",
        "worktree_root": str(Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics/lagrangian-fluid-lab")),
        "independent_case_count_increment": 0,
        "input_files": input_files,
        "input_sha256": input_sha,
        "deferred_input_files": [str(gencase["generated_xml"]), str(gencase["generated_bi4"])],
        "deferred_input_sha256": {str(gencase["generated_xml"]): gencase["generated_xml_sha256"], str(gencase["generated_bi4"]): None},
        "deferred_bi4_producer_sha256": {str(gencase["generated_bi4"]): gencase["generated_bi4_producer_sha256"]},
        "gencase_receipt": gencase["gencase_receipt"],
        "gencase_receipt_sha256": gencase["gencase_receipt_sha256"],
        "gencase_actual_evidence": {
            "per_case_receipt": gencase["gencase_receipt"],
            "per_case_receipt_sha256": gencase["gencase_receipt_sha256"],
            "generated_xml": {"path": gencase["generated_xml"], "producer_sha256": gencase["generated_xml_sha256"]},
            "generated_bi4": {"path": gencase["generated_bi4"], "producer_sha256": gencase["generated_bi4_producer_sha256"], "content_rehashed_by_source": False, "size_bytes_from_stat": gencase["generated_bi4_size_bytes"]},
            "total_particles": gencase["total_particles"],
            "fluid_particles": gencase["fluid_particles"],
            "fixed_particles": gencase["fixed_particles"],
            "returncode": 0,
            "solver_dimension_from_gencase": 3,
            "subprocess_os_returncode_recorded": True,
        },
        "native_initial_qa": qa_refs,
        "child_input_manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "metadata_binding": {"path": str(metadata_path), "sha256": sha256(metadata_path)},
        "owner_binding": {"path": str(owner_path), "sha256": sha256(owner_path)},
        "physical_binding": owner["physical_binding"],
        "physical_binding_sha256": owner["physical_binding_sha256"],
        "physical_condition_sha256": owner["physical_condition_sha256"],
        "physical_case_id": owner["physical_binding"]["physical_case_id"],
        "topphysical_case_id": owner["topphysical_case_id"],
        "source_plan_condition_sha256": endpoint["source_plan_condition_sha256"],
        "root230": {
            "entry": root230["references"]["entry"],
            "profile": root230["profile"],
            "dataset_inventory_profile": root230["dataset_inventory_profile"],
            "home_policy": root230["references"]["home_policy"],
            "gpu_policy": root230["references"]["gpu_policy"],
            "effective_reservation_function_sha256": root230["effective_reservation_function_sha256"],
            "home_free_gib_floor": root230["home_free_gib_floor"],
            "nvme_free_gib_floor": root230["nvme_free_gib_floor"],
            "nvme_peak_gib": root230["nvme_peak_gib"],
            "solver_concurrency_cap": root230["solver_concurrency_cap"],
        },
        "root_gpu_selection_profile": root230["profile"],
        "root_solver_concurrency_cap": root230["solver_concurrency_cap"],
        "root_actual_launch_source": str(ROOT230_ENTRY),
        "root_inventory_policy_source_sha256": root230["references"]["home_policy"]["sha256"],
        "root_effective_reservation_function_sha256": root230["effective_reservation_function_sha256"],
        "root_dataset_inventory_profile": root230["dataset_inventory_profile"],
        "root_home_free_gib_floor": root230["home_free_gib_floor"],
        "root_nvme_free_gib_floor": root230["nvme_free_gib_floor"],
        "root_nvme_peak_gib": root230["nvme_peak_gib"],
        "solver_recipe": {
            "dp_m": 0.01,
            "time_max_s": 1.2,
            "time_out_s": 0.001,
            "native_frame_count": 1201,
            "solver_options": ["-tmax:1.2", "-tout:0.001"],
            "no_mdbc": True,
            "no_forcing": True,
            "native_types": {"fixed": [0], "floating": [], "fluid": [3], "moving": []},
        },
        "qualification_scope": {
            "recipe_id": "F4_finite_drop_pool_native_dbc_verlet_wendland_v1",
            "resolution": "native_dp010",
            "expected_frames": 1201,
            "time_window_s": 1.2,
            "output_interval_s": 0.001,
            "mechanism_id": "finite_drop_pool",
            "status": "disabled_pending_root_review_after_root237_initial_native_qa",
        },
        "read_policy": {"source_arrays": False, "csv": False, "h5": False, "native_bi4": "deferred solver input after Root enables", "rendering": False},
        "resource_contract": {
            "native_concurrency": 8,
            "conversion_concurrency": 2,
            "cpu_threads": 2,
            "home_free_gib_floor": 500,
            "nvme_free_gib_floor": 100,
            "nvme_peak_gib": 24,
            "parent_budget_gpu_hours": 512,
            "parent_budget_cpu_core_hours": 3840,
            "qualification_slots": 1024,
            "production_slots": 720,
            "resource_window_approval": str(RESOURCE_WINDOW),
            "gpu_policy_entry": str(ROOT230_ENTRY),
        },
        "root235_root236_failures_preserved": str(evidence_path),
        "claim_boundary": "Actual GenCase and Root237 initial native input QA only; no full solver, visual, precision, Q-N, production, or independent-case credit.",
        "precision_status": "not_accepted",
        "q_n_status": "not_assessed",
        "production_approval": "none",
        "expected_outputs": {
            "output_root": "{attempt_root}",
            "data_root": "{attempt_root}/solver_output/data",
            "execution_receipt": "{attempt_root}/execution-receipt.json",
            "execution_receipt_sha256": None,
            "full_native_frames": 1201,
            "all_future_sha256": None,
        },
    }


def failure_record(root: Path, label: str) -> dict[str, Any]:
    receipt_path = root / "execution-receipt.json"
    stdout_path = root / "stdout.log"
    receipt = load_json(receipt_path)
    stdout = load_json(stdout_path)
    return {
        "label": label,
        "attempt_id": receipt.get("request", {}).get("attempt_id"),
        "receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)},
        "stdout": {"path": str(stdout_path), "sha256": sha256(stdout_path)},
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "error_type": stdout.get("error_type"),
        "error": stdout.get("error"),
        "arrays_read_by_source": stdout.get("arrays_read_by_source"),
        "preserved_without_promotion": stdout.get("parent_receipt_preserved") is True or receipt.get("status") == "failed",
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    plan_path = args.plan.resolve()
    plan = load_json(plan_path)
    endpoints = endpoint_map(plan)
    build_receipt_path = FRESH087 / "source-build-receipt.json"
    binding_path = args.gencase_binding.resolve()
    gencase_binding = load_json(binding_path)
    gencase_rows = verify_gencase(gencase_binding, endpoints)
    qa = verify_qa(args.qa_root.resolve(), gencase_rows)
    root230 = verify_root230()
    # Owner and source XML checks close the physical/source lineage before any
    # request is emitted.
    owners: dict[str, dict[str, Any]] = {}
    metadata: dict[str, dict[str, Any]] = {}
    for eid, endpoint in endpoints.items():
        owner_path = FRESH087 / "owners" / f"{eid}.owner.json"
        metadata_path = FRESH087 / "metadata" / f"{eid}.metadata.json"
        definition_path = FRESH087 / str(endpoint["source_definition_output"])
        owner = load_json(owner_path)
        meta = load_json(metadata_path)
        if owner.get("source_only") is not True or owner.get("launch_allowed") is not False:
            raise ValueError(f"{eid}: owner launch contract drift")
        if owner.get("physical_binding_sha256") != csha(owner.get("physical_binding")):
            raise ValueError(f"{eid}: physical binding digest drift")
        if owner.get("physical_condition_sha256") != endpoint.get("physical_condition_sha256"):
            raise ValueError(f"{eid}: source plan condition drift")
        if meta.get("physical_binding") != owner.get("physical_binding") or meta.get("source_only") is not True:
            raise ValueError(f"{eid}: source metadata physical binding drift")
        if sha256(definition_path) != endpoint.get("source_definition_sha256"):
            raise ValueError(f"{eid}: source Definition digest drift")
        owners[eid] = owner
        metadata[eid] = meta
    evidence_path = output / "evidence/root235-root236-root237-status.json"
    evidence = {
        "schema": "ds02.f4.root235-root236-root237.qa-lineage-evidence.v1",
        "family_id": "F4",
        "scope_id": "root_followup_089_stage1_f4_root237_qa_full1201_bind_v1",
        "root235": failure_record(ROOT235, "root235_missing_gencase_receipt_alias"),
        "root236": failure_record(ROOT236, "root236_wrong_historical_gencase_receipt_alias"),
        "root237": {
            "attempt_id": QA_ATTEMPT,
            "execution_receipt": qa["execution_receipt"],
            "index": qa["index"],
            "binding": qa["binding"],
            "producer_summary": qa["producer_summary"],
            "status": qa["status"],
            "case_count": qa["case_count"],
            "pass": True,
            "arrays_read_by_source": False,
            "arrays_read_by_job": True,
            "claim_boundary": qa["claim_boundary"],
        },
        "root216_negative_evidence_preserved": gencase_binding.get("root216_failure_evidence"),
        "root227_individual_gencase_parent_not_promoted": gencase_binding.get("aggregate_execution_receipt"),
        "independent_case_count_increment": 0,
        "no_jobs_started_by_source": True,
    }
    write_json(evidence_path, evidence)
    manifest_paths: dict[str, Path] = {}
    requests: dict[str, Path] = {}
    rows = []
    for eid, endpoint in endpoints.items():
        manifest = make_manifest(eid, plan, gencase_rows[eid], qa, root230)
        manifest_path = output / "manifests" / f"{eid}.json"
        write_json(manifest_path, manifest)
        manifest_paths[eid] = manifest_path
    builder_path = Path(__file__).resolve()
    preflight_path = PACKAGE / "workers/preflight_f4_root237_child_inputs_v1.py"
    for eid, endpoint in endpoints.items():
        owner_path = FRESH087 / "owners" / f"{eid}.owner.json"
        metadata_path = FRESH087 / "metadata" / f"{eid}.metadata.json"
        definition_path = FRESH087 / str(endpoint["source_definition_output"])
        request = make_request(eid, endpoint, owners[eid], metadata[eid], gencase_rows[eid], qa, manifest_paths[eid], evidence_path, root230, plan_path, build_receipt_path, owner_path, metadata_path, definition_path, binding_path, Path(str(gencase_binding.get("registered_root_index"))), builder_path, preflight_path)
        request_path = output / "requests" / f"{eid}-full1201-native-qualification.request.json"
        write_json(request_path, request)
        requests[eid] = request_path
        rows.append({
            "endpoint_id": eid,
            "gap_m": endpoint["gap_m"],
            "physical_condition_sha256": endpoint["physical_condition_sha256"],
            "gencase_receipt_sha256": gencase_rows[eid]["gencase_receipt_sha256"],
            "qa_report_sha256": qa["cases"][eid]["report_sha256"],
            "request": str(request_path),
            "request_sha256": sha256(request_path),
            "manifest": str(manifest_paths[eid]),
            "manifest_sha256": sha256(manifest_paths[eid]),
            "launch_allowed": False,
        })
    index = {
        "schema": "ds02.f4.root237-root230-full1201-request-index.v1",
        "scope_id": "root_followup_089_stage1_f4_root237_qa_full1201_bind_v1",
        "family_id": "F4",
        "case_count": 6,
        "qa_provider": {"attempt_id": QA_ATTEMPT, "execution_receipt": qa["execution_receipt"], "index": qa["index"], "binding": qa["binding"], "status": "completed_pass"},
        "root230": root230,
        "rows": rows,
        "launch_allowed": False,
        "independent_case_count_increment": 0,
        "future_native_receipt_sha256": None,
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "root235_root236_failures_preserved": str(evidence_path),
    }
    write_json(output / "requests/index.json", index)
    source_binding = {
        "schema": "ds02.f4.root237-root230-full1201-source-binding.v1",
        "scope_id": "root_followup_089_stage1_f4_root237_qa_full1201_bind_v1",
        "family_id": "F4",
        "claim_boundary": "Actual Root227 GenCase and Root237 native initial QA are bound; six Root230 qualification requests are disabled and require Root review.",
        "source_plan": {"path": str(plan_path), "sha256": sha256(plan_path)},
        "source_build_receipt": {"path": str(build_receipt_path), "sha256": sha256(build_receipt_path)},
        "gencase_binding": {"path": str(binding_path), "sha256": sha256(binding_path)},
        "registered_root_index": {"path": str(Path(str(gencase_binding.get("registered_root_index")))), "sha256": gencase_binding.get("registered_root_index_sha256")},
        "root237_qa": {"attempt_id": QA_ATTEMPT, "execution_receipt": qa["execution_receipt"], "index": qa["index"], "binding": qa["binding"], "producer_summary": qa["producer_summary"], "status": "completed_pass"},
        "root230": root230,
        "root235_root236_failures": str(evidence_path),
        "builder": {"path": str(builder_path), "sha256": sha256(builder_path)},
        "child_preflight": {"path": str(preflight_path), "sha256": sha256(preflight_path)},
        "rows": rows,
        "independent_case_count_increment": 0,
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "future_native_receipt_sha256": None,
    }
    preflight_index = output / "evidence/child-input-preflight-index.json"
    if preflight_index.is_file():
        source_binding["child_input_preflight_index"] = {
            "path": str(preflight_index),
            "sha256": sha256(preflight_index),
            "status": "completed",
            "case_count": 6,
            "arrays_read_by_source": False,
        }
    write_json(output / "source-binding.json", source_binding)
    return {"schema": source_binding["schema"], "status": "completed", "case_count": 6, "output": str(output), "qa_attempt": QA_ATTEMPT, "launch_allowed": False, "arrays_read_by_source": False, "jobs_started_by_source": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=FRESH087 / "source-plan.json")
    parser.add_argument("--gencase-binding", type=Path, default=GENCASE_BINDING)
    parser.add_argument("--qa-root", type=Path, default=QA_ROOT)
    parser.add_argument("--output", type=Path, default=PACKAGE)
    args = parser.parse_args()
    result = build(args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
