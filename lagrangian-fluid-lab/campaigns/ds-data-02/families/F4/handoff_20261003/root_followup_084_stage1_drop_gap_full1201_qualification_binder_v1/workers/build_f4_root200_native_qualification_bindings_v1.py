#!/usr/bin/env python3
"""Build disabled F4 Root200 qualification bindings from frozen small metadata.

The builder reads JSON/XML metadata and per-case GenCase receipts only.  It
never opens, hashes, copies, or decodes a BI4, and it never launches a job or
writes a shared registry.  Root may rerun it after the corrected Root212
native-QA producer has emitted a completed0/pass index and binding.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "ds02.f4.root200.native-qualification-binder.v1"
PACKAGE = Path(__file__).resolve().parent.parent
FRESH081 = PACKAGE.parent / "root_followup_081_stage1_drop_gap_internal8_source_v1"
FRESH082 = PACKAGE.parent / "root_followup_082_stage1_drop_gap_native_qa_assembler_v1"
FRESH083 = PACKAGE.parent / "root_followup_083_stage1_drop_gap_native_qa_producer_v1"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
F4_WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics")
ROOT195 = DATA_ROOT / "families/F4/F4_INTERNAL_GAP8_DP010/root-stage1-f4-internal8-genuine-gencase-195"
ROOT196_ATTEMPT = "root-stage1-f4-internal8-native-initial-qa-196"
ROOT210_ATTEMPT = "root-stage1-f4-internal8-native-initial-qa-source-binding-repair-210"
ROOT211_ATTEMPT = "root-stage1-f4-internal8-native-initial-qa-source-binding-repair-211"
ROOT212_ATTEMPT = "root-stage1-f4-internal8-native-initial-qa-212"
ROOT216_ATTEMPT = "root-stage1-f4-internal8-native-initial-qa-metadata-contract-repair-216"
ACCEPTED_QA_ATTEMPTS = (ROOT210_ATTEMPT, ROOT211_ATTEMPT, ROOT212_ATTEMPT, ROOT216_ATTEMPT)
QA_CASE = "F4_INTERNAL_GAP8_DP010_INITIAL_QA"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
POLICY = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
QUAL_ENTRY = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_actual_qualifications_strict_entry_146/launch.py"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
GOAL = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
RESOURCE_WINDOW = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"


def sha256(path: Path) -> str:
    if path.suffix.lower() in {".bi4", ".h5", ".vtk", ".csv"}:
        raise ValueError(f"source binder refuses scientific array artifact: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require_file(path: Path, *, hashable: bool = True) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    if hashable:
        sha256(path)
    return path


def future_qa(provider_attempt: str) -> dict[str, Any]:
    root = DATA_ROOT / "families/F4" / QA_CASE / provider_attempt
    return {
        "provider_attempt_id": provider_attempt,
        "execution_receipt": str(root / "execution-receipt.json"),
        "execution_receipt_sha256": None,
        "index": str(root / "initial-native-qa-index.json"),
        "index_sha256": None,
        "binding": str(root / "initial-native-qa-binding.json"),
        "binding_sha256": None,
        "per_case_report_directory": str(root / "native-audit/cases"),
        "required": "completed0 execution receipt, completed/pass index, pass binding, and eight pass reports",
        "status": f"future_{provider_attempt}_cpu_audit",
    }


def validate_root195() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    source_plan_path = FRESH081 / "source-plan.json"
    source_receipt_path = FRESH081 / "source-build-receipt.json"
    producer_binding_path = FRESH083 / "evidence/root195-producer-input-binding.json"
    source_plan = load_json(require_file(source_plan_path))
    source_receipt = load_json(require_file(source_receipt_path))
    producer = load_json(require_file(producer_binding_path))
    parent = producer["aggregate_execution_receipt"]
    if parent.get("status") != "failed" or parent.get("returncode") != 0:
        raise ValueError("Root195 aggregate receipt must remain failed with returncode 0")
    if parent.get("error") != "GenCase actual particle count missing":
        raise ValueError("Root195 aggregate postcheck error changed")
    if parent.get("preserved_without_promotion") is not True:
        raise ValueError("Root195 failed aggregate is not marked preserved")
    member_report = producer["aggregate_member_report"]
    if member_report.get("status") != "completed" or member_report.get("endpoint_count") != 8:
        raise ValueError("Root195 member report is not the expected eight-case report")
    endpoints = source_plan.get("endpoints")
    rows = producer.get("per_case_actual_gencase_receipts")
    if not isinstance(endpoints, list) or len(endpoints) != 8 or not isinstance(rows, list) or len(rows) != 8:
        raise ValueError("Root195/source plan does not contain exactly eight endpoints")
    by_id = {str(row["endpoint_id"]): row for row in rows}
    for endpoint in endpoints:
        eid = str(endpoint["endpoint_id"])
        row = by_id.get(eid)
        if row is None:
            raise ValueError(f"missing Root195 row: {eid}")
        receipt_ref = row["gencase_receipt"]
        receipt_path = Path(str(receipt_ref["path"]))
        receipt = load_json(require_file(receipt_path))
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise ValueError(f"{eid}: per-case GenCase receipt is not completed0")
        if receipt.get("individual_GenCase_OS_returncode_recorded_from_subprocess") is not True:
            raise ValueError(f"{eid}: per-case subprocess OS0 provenance is missing")
        if receipt.get("solver_dimension_from_gencase") != 3:
            raise ValueError(f"{eid}: per-case GenCase is not 3-D")
        if receipt_ref.get("sha256") != sha256(receipt_path):
            raise ValueError(f"{eid}: per-case receipt SHA drift")
        if row.get("physical_condition_sha256") != endpoint.get("physical_condition_sha256"):
            raise ValueError(f"{eid}: physical condition drift")
        for output_key, suffix in (("generated_xml", ".xml"), ("generated_bi4", ".bi4")):
            output = row[output_key]
            output_path = Path(str(output["path"]))
            require_file(output_path, hashable=output_path.suffix.lower() != ".bi4")
            if not str(output_path).endswith(f"/{eid}{suffix}"):
                raise ValueError(f"{eid}: generated output path drift")
            if output_key == "generated_bi4" and output.get("content_rehashed_by_source") is not False:
                raise ValueError(f"{eid}: source must not claim BI4 rehash")
            if not isinstance(output.get("producer_sha256"), str) or len(output["producer_sha256"]) != 64:
                raise ValueError(f"{eid}: missing producer-declared {output_key} SHA")
        counts = row.get("counts")
        if not isinstance(counts, dict) or any(not isinstance(counts.get(k), int) or counts[k] <= 0 for k in ("total", "fluid", "fixed")):
            raise ValueError(f"{eid}: dynamic counts missing")
        if counts["fluid"] + counts["fixed"] != counts["total"]:
            raise ValueError(f"{eid}: dynamic count partition does not close")
        if receipt.get("total_particles") != counts["total"] or receipt.get("fluid_particles") != counts["fluid"] or receipt.get("fixed_particles") != counts["fixed"]:
            raise ValueError(f"{eid}: per-case receipt counts differ from producer evidence")
    return source_plan, source_receipt, rows


def qa_binding(args: argparse.Namespace) -> dict[str, Any]:
    if not any((args.qa_index, args.qa_binding, args.qa_receipt)):
        return future_qa(ROOT216_ATTEMPT)
    if not all((args.qa_index, args.qa_binding, args.qa_receipt)):
        raise ValueError("--qa-index, --qa-binding, and --qa-receipt must be supplied together")
    index_path = Path(args.qa_index)
    binding_path = Path(args.qa_binding)
    receipt_path = Path(args.qa_receipt)
    if not all(any(attempt in str(path) for attempt in ACCEPTED_QA_ATTEMPTS) for path in (index_path, binding_path, receipt_path)):
        raise ValueError("only an actual completed/pass Root212/Root216 (or explicitly reviewed corrected attempt) can enable the binder; Root196/210/211 failure evidence remains preserved")
    receipt = load_json(require_file(receipt_path))
    index = load_json(require_file(index_path))
    binding = load_json(require_file(binding_path))
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("native QA execution receipt is not completed0")
    if index.get("status") not in {"completed", "pass"} or index.get("pass") is not True or index.get("case_count") != 8:
        raise ValueError("native QA index is not an eight-case pass")
    if binding.get("status") not in {"pass", "completed"}:
        raise ValueError("native QA binding is not passing")
    rows = index.get("cases")
    if not isinstance(rows, list) or len(rows) != 8 or any(row.get("pass") is not True for row in rows):
        raise ValueError("native QA index lacks eight passing case rows")
    provider_attempt = next(attempt for attempt in ACCEPTED_QA_ATTEMPTS if attempt in str(index_path))
    return {
        "provider_attempt_id": provider_attempt,
        "execution_receipt": str(receipt_path),
        "execution_receipt_sha256": sha256(receipt_path),
        "index": str(index_path),
        "index_sha256": sha256(index_path),
        "binding": str(binding_path),
        "binding_sha256": sha256(binding_path),
        "per_case_report_directory": str(index_path.parent / "native-audit/cases"),
        "required": "completed0 execution receipt, completed/pass index, pass binding, and eight pass reports",
        "status": f"actual_{provider_attempt}_pass",
    }


def source_files(endpoint_id: str, owner: dict[str, Any], metadata: dict[str, Any], builder: Path) -> list[Path]:
    files = [
        FRESH081 / "source-plan.json",
        FRESH081 / "source-build-receipt.json",
        FRESH083 / "source-binding.json",
        FRESH083 / "evidence/root195-producer-input-binding.json",
        FRESH083 / "workers/run_f4_native_initial_qa_producer_v1.py",
        FRESH082 / "source-binding.json",
        FRESH082 / "workers/assemble_f4_initial_native_qa_v1.py",
        FRESH082 / "workers/validate_f4_initial_native_v4.py",
        Path(owner["source_definition"]["path"]),
        Path(metadata["source_definition"]["path"]),
        Path(owner["source_definition"]["mother_path"]),
        INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        POLICY,
        QUAL_ENTRY,
        GOAL,
        RESOURCE_WINDOW,
        SOLVER,
        builder,
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in files:
        path = path.resolve()
        key = str(path)
        if key not in seen:
            require_file(path)
            unique.append(path)
            seen.add(key)
    return unique


def build_request(endpoint: dict[str, Any], owner: dict[str, Any], metadata: dict[str, Any], row: dict[str, Any], qa: dict[str, Any], builder: Path) -> dict[str, Any]:
    eid = str(endpoint["endpoint_id"])
    attempt = f"root-stage1-f4-f4-drop-internal-gap{eid.split('GAP', 1)[1].split('_DP', 1)[0].lower()}_dp010-full1201-native-qualification-200"
    # The source case IDs use the stable 0pNN500 spelling; derive the exact
    # attempt spelling from the endpoint ID rather than from a mother case.
    gap_token = eid.split("GAP", 1)[1].split("_DP", 1)[0].lower()
    attempt = f"root-stage1-f4-f4-drop-internal-gap{gap_token}-dp010-full1201-native-qualification-200"
    gencase = row["gencase_receipt"]
    gencase_path = Path(str(gencase["path"])).resolve()
    case_dir = gencase_path.parent
    prefix = case_dir / eid
    output_root = DATA_ROOT / "families/F4" / eid / attempt
    owner_path = Path(owner["source_definition"]["path"]).resolve()
    metadata_path = Path(metadata["source_definition"]["path"]).resolve()
    files = source_files(eid, owner, metadata, builder)
    if gencase_path not in files:
        files.append(gencase_path)
    input_hashes = {str(path): sha256(path) for path in files}
    parent_path = ROOT195 / "execution-receipt.json"
    report_path = ROOT195 / "gencase-preflight-result.json"
    xml_path = Path(str(row["generated_xml"]["path"])).resolve()
    bi4_path = Path(str(row["generated_bi4"]["path"])).resolve()
    qa_reports = Path(qa["per_case_report_directory"]) / eid / "native-preflight-audit.json"
    deferred = [parent_path, report_path, gencase_path, xml_path, bi4_path, qa_reports, Path(qa["execution_receipt"]), Path(qa["index"]), Path(qa["binding"])]
    deferred_hashes = {
        str(parent_path): sha256(parent_path),
        str(report_path): sha256(report_path),
        str(gencase_path): gencase["sha256"],
        str(xml_path): row["generated_xml"]["producer_sha256"],
        str(bi4_path): None,
        str(qa_reports): None,
        str(Path(qa["execution_receipt"])): qa["execution_receipt_sha256"],
        str(Path(qa["index"])): qa["index_sha256"],
        str(Path(qa["binding"])): qa["binding_sha256"],
    }
    physical = owner["physical_binding"]
    count = row["counts"]
    root196 = future_qa(ROOT196_ATTEMPT)
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F4",
        "case_id": eid,
        "attempt_id": attempt,
        "kind": "qualification",
        "cpu_task_kind": "native_solver",
        "cpu_threads": 2,
        "command": [str(SOLVER), str(prefix), "{attempt_root}/solver_output", "-tmax:1.2", "-tout:0.001"],
        "cwd": str(case_dir),
        "worktree_root": str(F4_WORKTREE.resolve()),
        "gencase_receipt": str(gencase_path),
        "gencase_receipt_sha256": gencase["sha256"],
        "gencase_actual_evidence": {
            "per_case_receipt": str(gencase_path),
            "per_case_receipt_sha256": gencase["sha256"],
            "returncode": 0,
            "subprocess_os_returncode_recorded": True,
            "solver_dimension_from_gencase": 3,
            "total_particles": count["total"],
            "fluid_particles": count["fluid"],
            "fixed_particles": count["fixed"],
            "generated_xml": {"path": str(xml_path), "producer_sha256": row["generated_xml"]["producer_sha256"]},
            "generated_bi4": {"path": str(bi4_path), "producer_sha256": row["generated_bi4"]["producer_sha256"], "content_rehashed_by_source": False},
        },
        "root195_parent_aggregate": {
            "path": str(parent_path),
            "sha256": "5e85c8b688e994eabed98423af424b49a5f2324cf50e88129dcf82016d6a6c5b",
            "status": "failed",
            "returncode": 0,
            "error": "GenCase actual particle count missing",
            "preserved_without_promotion": True,
        },
        "native_initial_qa": qa,
        "original_root196_failed_qa": {
            **root196,
            "status": "preserved_failed_or_superseded",
            "accepted_as_dependency": False,
            "failure_reason": "Root196 rejected the adopted source binding; Root210 failed before arrays on aggregate producer path drift; Root211 failed before usable QA because the BI4 lacked raw Mk/Type arrays; Root212 then failed before arrays on a nested generated_bi4 adapter-key bug. Root216 must use the XML/UID-derived partition, the raw Posd/Idp audit contract, and the repaired metadata/row adapter.",
        },
        "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": owner["physical_condition_sha256"],
        "physical_binding_sha256": owner["physical_binding_sha256"],
        "physical_binding": physical,
        "topphysical_case_id": owner["topphysical_case_id"],
        "source_plan_condition_sha256": owner["source_plan_condition_sha256"],
        "owner_binding": {"path": str((FRESH081 / "owners" / f"{eid}.owner.json").resolve()), "sha256": sha256(FRESH081 / "owners" / f"{eid}.owner.json")},
        "metadata_binding": {"path": str((FRESH081 / "metadata" / f"{eid}.metadata.json").resolve()), "sha256": sha256(FRESH081 / "metadata" / f"{eid}.metadata.json")},
        "deferred_input_files": [str(path) for path in deferred],
        "deferred_input_sha256": deferred_hashes,
        "deferred_bi4_producer_sha256": {str(bi4_path): row["generated_bi4"]["producer_sha256"]},
        "input_files": [str(path) for path in files],
        "input_sha256": input_hashes,
        "expected_outputs": {
            "output_root": str(output_root),
            "data_root": str(output_root / "solver_output/data"),
            "execution_receipt": str(output_root / "execution-receipt.json"),
            "execution_receipt_sha256": None,
            "full_native_frames": 1201,
            "future_sha256_values": "null until Root actual qualification completion",
        },
        "solver_recipe": {
            "full_native_frames": 1201,
            "time_max_s": 1.2,
            "save_interval_s": 0.001,
            "native_types": {"fixed": [0], "moving": [], "floating": [], "fluid": [3]},
            "no_forcing": True,
            "no_mdbc": True,
            "solver_options": ["-tmax:1.2", "-tout:0.001"],
        },
        "qualification_scope": {
            "mechanism_id": "finite_drop_pool",
            "resolution": "native_dp010",
            "recipe_id": "F4_finite_drop_pool_native_dbc_verlet_wendland_v1",
            "expected_frames": 1201,
            "time_window_s": 1.2,
            "output_interval_s": 0.001,
            "status": "disabled_pending_Root216_XML_UID_metadata_repair_native_initial_QA",
        },
        "scientific_scope": {
            "physical_case_id": physical["physical_case_id"],
            "physical_binding_sha256": owner["physical_binding_sha256"],
            "gap_m": physical["parameters"]["gap_m"],
            "original_controls_and_complete_physical_window_retained": True,
            "independent_case_count_increment": 0,
            "qualification_status": "unqualified; disabled; no Q-N, precision, visual, or production claim",
            "production_approval": "none",
        },
        "read_policy": {"source_arrays": False, "csv": False, "h5": False, "native_bi4": "solver input after Root enables request", "rendering": False},
        "estimated_peak_gpu_mib": 8192,
        "estimated_storage_bytes": 214748364800,
        "max_wall_seconds": 14400,
        "resource_contract": {
            "cpu_threads": 2,
            "native_concurrency": 8,
            "conversion_concurrency": 2,
            "home_free_gib_floor": 500,
            "nvme_free_gib_floor": 100,
            "nvme_peak_gib": 24,
            "parent_budget_gpu_hours": 512,
            "parent_budget_cpu_core_hours": 3840,
            "qualification_slots": 1024,
            "production_slots": 720,
            "gpu_policy_entry": str(QUAL_ENTRY),
            "resource_window_approval": str(RESOURCE_WINDOW),
        },
        "scope_id": "root_followup_084_stage1_drop_gap_full1201_qualification_binder_v1",
        "launch": False,
        "launch_allowed": False,
        "launch_owner": "root",
        "root_review_required": True,
        "source_only": True,
        "status": "source_only_disabled",
        "disabled_reason": "Root200 may be enabled only after Root216 actual XML/UID-derived native initial QA completed0/pass index, binding, and eight per-case reports; raw Mk/Type is not claimed, Root195 aggregate failure and Root196/210/211/212 failed receipts remain immutable, and the native recipe stays exact.",
        "independent_case_count_increment": 0,
        "precision_status": "not_accepted",
        "q_n_status": "not_assessed",
        "production_approval": "none",
    }


def assemble(args: argparse.Namespace) -> dict[str, Any]:
    source_plan, source_receipt, rows = validate_root195()
    qa = qa_binding(args)
    row_map = {str(row["endpoint_id"]): row for row in rows}
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    requests = []
    for endpoint in source_plan["endpoints"]:
        eid = str(endpoint["endpoint_id"])
        owner_path = FRESH081 / "owners" / f"{eid}.owner.json"
        metadata_path = FRESH081 / "metadata" / f"{eid}.metadata.json"
        owner = load_json(require_file(owner_path))
        metadata = load_json(require_file(metadata_path))
        request = build_request(endpoint, owner, metadata, row_map[eid], qa, Path(__file__).resolve())
        path = out_dir / f"{eid}-full1201-native-qualification.request.json"
        write_json(path, request)
        requests.append({"case_id": eid, "path": str(path), "sha256": sha256(path), "status": request["status"], "physical_case_id": request["physical_case_id"], "physical_condition_sha256": request["physical_condition_sha256"], "gencase_receipt_sha256": request["gencase_receipt_sha256"], "native_initial_qa_provider_attempt_id": qa["provider_attempt_id"]})
    index = {
        "schema": "ds02.f4.root200.native-qualification-request-index.v1",
        "scope_id": "root_followup_084_stage1_drop_gap_full1201_qualification_binder_v1",
        "family_id": "F4",
        "case_count": 8,
        "status": "source_only_disabled",
        "launch_allowed": False,
        "independent_case_count_increment": 0,
        "root195_parent_preserved_failed": True,
        "root195_parent_error": "GenCase actual particle count missing",
        "native_initial_qa_dependency": qa,
        "requests": requests,
        "solver_recipe": {"time_max_s": 1.2, "save_interval_s": 0.001, "full_native_frames": 1201, "solver_options": ["-tmax:1.2", "-tout:0.001"], "no_forcing": True, "no_mdbc": True},
        "dynamic_counts_source": "Root195 per-case gencase-receipt.json / producer evidence; no mother count is substituted",
        "source_only_read_policy": {"bi4_arrays_read": False, "bi4_hashed_by_source": False, "jobs_started": False, "shared_state_written": False},
    }
    write_json(out_dir / "index.json", index)
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=PACKAGE / "requests")
    parser.add_argument("--qa-index", type=Path)
    parser.add_argument("--qa-binding", type=Path)
    parser.add_argument("--qa-receipt", type=Path)
    args = parser.parse_args()
    index = assemble(args)
    print(json.dumps({"schema": SCHEMA, "status": index["status"], "case_count": index["case_count"], "qa_provider_attempt_id": index["native_initial_qa_dependency"]["provider_attempt_id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
