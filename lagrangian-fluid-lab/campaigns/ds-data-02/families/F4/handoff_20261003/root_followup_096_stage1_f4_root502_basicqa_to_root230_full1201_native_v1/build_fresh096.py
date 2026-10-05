#!/usr/bin/env python3
"""Build the disabled F4 Root502-basic-QA -> Root230 native handoff.

This builder consumes only JSON/XML/Python metadata and the already registered
Root502 basic-QA receipts/reports.  It never opens, copies, or hashes a BI4,
VTK, H5, CSV, DAT, or solver output.  The native requests remain disabled;
Root owns any later enablement and UUID lease selection.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
PACKAGE = Path(__file__).resolve().parent
FRESH095 = PACKAGE.parent / "root_followup_095_stage1_f4_gencase_basic_initial_qa_v1"
FRESH094 = PACKAGE.parent / "root_followup_094_stage1_f4_basic_native_input_qa_v1"
ROOT502 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_presolver_basicQA_decoder_binding_alias_repair_502"
ROOT503 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_basicQA502_first1_then_cap4_controller_503/controller-result.json"
ROOT504 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_actual_presolver_basicQA502_all24_terminal_review_504/actual-root-presolver-basicQA-all24-review.json"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT134 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
RESOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64").resolve()
FRESH095_PLAN = FRESH095 / "metadata/fresh095-gencase-plan.json"
FRESH095_STAGE = FRESH095 / "metadata/fresh095-stage1-contract.json"
FRESH095_READER = FRESH095 / "metadata/fresh095-partvtk-contract.json"
FRESH095_EVIDENCE = FRESH095 / "metadata/fresh095-root44424-evidence.json"
FRESH095_WORKER = FRESH095 / "workers/run_f4_fresh095_gencase_basic_initial_qa.py"
FRESH094_MANIFEST = FRESH094 / "F4_STAGE1_FRESH094_BASIC_NATIVE_INPUT_QA_MANIFEST.json"
ROOT230_ENTRY = ROOT230 / "launch.py"
ROOT230_HOME = ROOT230 / "root_native_home_floor_inventory_policy.py"
ROOT230_CONTRACT = ROOT230 / "source-policy-contract.json"
ROOT230_GPU = ROOT134 / "ds02_root_all_idle_gpu_policy_v2.py"
SCOPE_ID = "F4_STAGE1_ROOT502_BASIC_QA_TO_ROOT230_FULL1201_NATIVE_V1"
ROOT502_SCOPE = "root_stage1_f4_presolver_basicQA_decoder_binding_alias_repair_502"
ROOT230_PROFILE = "root_live_all_idle_uuid_leased_eight_solver_v2"
ROOT230_DATASET_PROFILE = "root_home_floor_no_legacy_dataset_walk_native_v1"
ROOT230_EFFECTIVE_RESERVATION_SHA = "46e62ea197862a833797556d09350126b3632b2e3b1d496d08816ee42f7abecf"
ROOT230_ENTRY_SHA = "7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e"
ROOT230_HOME_SHA = "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5"
ROOT230_GPU_SHA = "4e6f340222f7823ae9df1a145ccda884dcf401c9740fc78c51a88066ae1c88cd"
STRICT_SHA = "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"
RAW_SUFFIXES = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv", ".dat"}
STATIC_SUFFIXES = {".json", ".jsonl", ".xml", ".py", ".md", ".txt", ".log", ".linux64", ""}
HEX = set("0123456789abcdef")


def load(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
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
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ref(path: Path) -> dict[str, str]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path)}


def unique(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        path = Path(path).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX


def verify_root230() -> dict[str, Any]:
    for path in (ROOT230_ENTRY, ROOT230_HOME, ROOT230_CONTRACT, ROOT230_GPU, RUNTIME, STRICT, RESOURCE, SOLVER):
        if not path.is_file():
            raise FileNotFoundError(path)
    contract = load(ROOT230_CONTRACT)
    refs = {
        "entry": ref(ROOT230_ENTRY),
        "home_policy": ref(ROOT230_HOME),
        "gpu_policy": ref(ROOT230_GPU),
        "contract": ref(ROOT230_CONTRACT),
        "runtime": ref(RUNTIME),
        "strict_dispatch": ref(STRICT),
        "resource_window": ref(RESOURCE),
        "solver": ref(SOLVER),
    }
    if contract.get("schema") != "ds02.root.native-home-floor-policy.v1":
        raise ValueError("Root230 contract schema drift")
    if contract.get("entry_sha256") != refs["entry"]["sha256"] or contract.get("new_policy_sha256") != refs["home_policy"]["sha256"]:
        raise ValueError("Root230 contract digest drift")
    if refs["entry"]["sha256"] != ROOT230_ENTRY_SHA or refs["home_policy"]["sha256"] != ROOT230_HOME_SHA or refs["gpu_policy"]["sha256"] != ROOT230_GPU_SHA:
        raise ValueError("Root230 reviewed source digest drift")
    if contract.get("runtime_file_unchanged") is not True or contract.get("source_only_no_jobs_started") is not True:
        raise ValueError("Root230 source policy drift")
    if "root_live_all_idle_uuid_leased_eight_solver_v2" not in ROOT230_GPU.read_text(encoding="utf-8"):
        raise ValueError("Root230 GPU profile drift")
    return {
        "profile": ROOT230_PROFILE,
        "dataset_inventory_profile": ROOT230_DATASET_PROFILE,
        "effective_reservation_function_sha256": ROOT230_EFFECTIVE_RESERVATION_SHA,
        "references": refs,
        "home_free_gib_floor": 500,
        "nvme_free_gib_floor": 100,
        "nvme_peak_gib": 24,
        "solver_concurrency_cap": 8,
        "foreign_gpu_protection": True,
        "uuid_selection": "resolve only at Root enable time from live inventory; source never selects a UUID",
    }


def verify_controller_and_review() -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    controller = load(ROOT503)
    review = load(ROOT504)
    if controller.get("requested") != 24 or controller.get("finished") != 24 or controller.get("completed0") != 24 or controller.get("pending_held") != 0:
        raise ValueError("Root503 controller is not the reported 24/24 completed-0 closure")
    if review.get("actual_basic_QA_completed0") != 24 or review.get("new_case_increment") != 0:
        raise ValueError("Root504 review closure drift")
    for key in ("source095_and_old500_first_decoder_KeyError_immutable", "old471_continuum_mass_and_exact_lattice_negative_preserved", "main_scientific_payloads_not_read_or_hashed", "complete_solver_and_postnative_frame0_velocity_remain_pending", "numerical_precision_QN_visual_production_not_certified"):
        if review.get(key) is not True:
            raise ValueError(f"Root504 boundary missing: {key}")
    rows = review.get("cases")
    if not isinstance(rows, list) or len(rows) != 24:
        raise ValueError("Root504 does not contain 24 case rows")
    mapped: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row["case_id"])
        if case_id in mapped:
            raise ValueError(f"duplicate Root504 case: {case_id}")
        for field in ("request", "actual_receipt", "actual_basicQA_report"):
            if not isinstance(row.get(field), dict) or not isinstance(row[field].get("path"), str) or not valid_sha(row[field].get("sha256")):
                raise ValueError(f"Root504 {case_id} lacks {field} reference")
        receipt_path = Path(row["actual_receipt"]["path"])
        report_path = Path(row["actual_basicQA_report"]["path"])
        receipt = load(receipt_path)
        report = load(report_path)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise ValueError(f"Root502 receipt is not completed/0: {case_id}")
        if report.get("status") != "completed" or report.get("returncode") != 0 or report.get("audit", {}).get("pass") is not True:
            raise ValueError(f"Root502 basic QA is not passed: {case_id}")
        checks = report.get("audit", {}).get("checks", {})
        if not checks or any(value is not True for value in checks.values()):
            raise ValueError(f"Root502 basic checks are not all true: {case_id}")
        if report.get("audit", {}).get("raw_mk_type_observed") is not False:
            raise ValueError(f"raw Mk/Type claim drift: {case_id}")
        request_path = Path(row["request"]["path"])
        request = load(request_path)
        if "root500-root502" not in str(request.get("attempt_id", "")):
            raise ValueError(f"not the Root502 derived attempt: {case_id}")
        command = request.get("command", [])
        if "--binding" not in command:
            raise ValueError(f"Root502 request has no binding: {case_id}")
        binding = load(Path(command[command.index("--binding") + 1]))
        if binding.get("decoder") != binding.get("reader", {}).get("safe_decoder_source"):
            raise ValueError(f"Root502 decoder alias is not exact: {case_id}")
        if not Path(row["actual_receipt"]["path"]).is_file() or not Path(row["actual_basicQA_report"]["path"]).is_file():
            raise FileNotFoundError(f"Root502 actual evidence missing: {case_id}")
        mapped[case_id] = {
            "review_row": row,
            "request_path": request_path.resolve(),
            "request": request,
            "binding_path": Path(command[command.index("--binding") + 1]).resolve(),
            "binding": binding,
            "receipt_path": receipt_path.resolve(),
            "receipt": receipt,
            "report_path": report_path.resolve(),
            "report": report,
        }
    return controller, review, mapped


def load_gencase_sources() -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    plan = load(FRESH095_PLAN)
    stage = load(FRESH095_STAGE)
    if plan.get("case_count") != 24 or stage.get("case_count") != 24:
        raise ValueError("fresh095 case count drift")
    plan_rows = {str(row["case_id"]): row for row in plan["cases"]}
    if len(plan_rows) != 24:
        raise ValueError("fresh095 case IDs are not unique")
    bindings: dict[str, dict[str, Any]] = {}
    sources: dict[str, dict[str, Any]] = {}
    for case_id, row in sorted(plan_rows.items()):
        binding_path = Path(row["binding"])
        binding = load(binding_path)
        if sha(binding_path) != row.get("binding_sha256"):
            raise ValueError(f"fresh095 binding digest drift: {case_id}")
        if binding.get("case_id") != case_id or binding.get("source_only") is not True or binding.get("execution_allowed") is not False:
            raise ValueError(f"fresh095 binding boundary drift: {case_id}")
        receipt_path = Path(binding["gencase_receipt"]["path"])
        receipt = load(receipt_path)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0 or receipt.get("solver_dimension_from_gencase") != 3:
            raise ValueError(f"GenCase receipt is not completed/0 3D: {case_id}")
        if not isinstance(receipt.get("total_particles"), int) or not isinstance(receipt.get("fluid_particles"), int):
            raise ValueError(f"GenCase receipt lacks actual counts: {case_id}")
        xml_path = Path(binding["generated_xml"]["path"])
        owner_path = Path(binding["source_owner"]["path"])
        definition_path = Path(binding["source_definition"]["path"])
        if xml_path.suffix.lower() != ".xml" or not xml_path.is_file():
            raise FileNotFoundError(xml_path)
        owner = load(owner_path)
        source = {
            "plan": row,
            "binding_path": binding_path.resolve(),
            "binding": binding,
            "receipt_path": receipt_path.resolve(),
            "receipt": receipt,
            "xml_path": xml_path.resolve(),
            "owner_path": owner_path.resolve(),
            "owner": owner,
            "definition_path": definition_path.resolve(),
            "bi4_path": Path(binding["generated_bi4"]["path"]).resolve(),
            "bi4_sha256": binding["generated_bi4"]["producer_sha256"],
            "xml_sha256": sha(xml_path),
            "owner_sha256": sha(owner_path),
            "definition_sha256": sha(definition_path),
            "receipt_sha256": sha(receipt_path),
            "report_path": Path(binding["prepared_report"]["path"]).resolve(),
            "report_sha256": binding["prepared_report"]["sha256"],
        }
        if source["xml_sha256"] != binding["generated_xml"]["sha256"]:
            raise ValueError(f"prepared XML digest drift: {case_id}")
        if source["receipt_sha256"] != binding["gencase_receipt"]["sha256"]:
            raise ValueError(f"GenCase receipt digest drift: {case_id}")
        if not valid_sha(source["bi4_sha256"]):
            raise ValueError(f"BI4 producer attestation missing: {case_id}")
        bindings[case_id] = binding
        sources[case_id] = source
    return plan, stage, bindings, sources


def root502_summary(case_id: str, qa: dict[str, Any]) -> dict[str, Any]:
    row = qa["review_row"]
    report = qa["report"]
    audit = report["audit"]
    return {
        "case_id": case_id,
        "attempt_id": qa["request"].get("attempt_id"),
        "request": ref(qa["request_path"]),
        "binding": ref(qa["binding_path"]),
        "execution_receipt": ref(qa["receipt_path"]),
        "basic_qa_report": ref(qa["report_path"]),
        "status": "completed",
        "returncode": 0,
        "pass": True,
        "checks_all_true": True,
        "actual_counts": {
            "total": audit.get("root_values", {}).get("CaseNp"),
            "fixed": audit.get("root_values", {}).get("CaseNfixed"),
            "fluid": audit.get("root_values", {}).get("CaseNfluid"),
            "dimension": 3,
            "data2d": audit.get("root_values", {}).get("Data2d"),
        },
        "raw_mk_type_observed": False,
        "source_type_partition": "derived from XML fixed/fluid blocks and initial Idp ranges; raw Mk/Type are not claimed",
        "mass_rescaled": False,
        "mass_policy": "diagnostic only; no continuum mass or exact lattice gate",
        "native_frame0_velocity": "deferred until native solver; fresh094 post-native contract",
        "source_recipe_unchanged": bool(row.get("source_recipe_unchanged")),
        "actual_gap": row.get("actual_gap"),
        "actual_inclusive_source_population": row.get("actual_inclusive_source_population"),
        "root502_request_lineage": "decoder alias repair derived from fresh095; Root500/501 failures remain historical and are not substitutes",
    }


def build() -> dict[str, Any]:
    PACKAGE.mkdir(parents=True, exist_ok=True)
    root230 = verify_root230()
    controller, review, qa_rows = verify_controller_and_review()
    plan, stage, bindings, sources = load_gencase_sources()
    if set(qa_rows) != set(sources):
        raise ValueError("Root502 QA and fresh095 case sets differ")
    resource = load(RESOURCE)
    fresh094_ref = ref(FRESH094_MANIFEST)
    root503_ref = ref(ROOT503)
    root504_ref = ref(ROOT504)

    root502_rows = [root502_summary(case_id, qa_rows[case_id]) for case_id in sorted(qa_rows)]
    root502_evidence_path = PACKAGE / "metadata/fresh096-root502-basicqa-evidence.json"
    dump(root502_evidence_path, {
        "schema": "ds02.f4.fresh096.root502-basicqa-evidence.v1",
        "scope_id": SCOPE_ID,
        "root502_scope": ROOT502_SCOPE,
        "controller": root503_ref,
        "review": root504_ref,
        "case_count": 24,
        "actual_basicQA_completed0": 24,
        "all_actual_basic_checks_true": True,
        "raw_mk_type_observed": False,
        "source_type_partition": "XML+UID derived only",
        "old500_old501_failures_preserved": True,
        "old471_strict_negative_preserved": True,
        "main_scientific_payloads_read_or_hashed_by_source": False,
        "native_and_postnative_status": "future; native solver and fresh094 frame0 downward-velocity audit remain pending",
        "new_case_increment": 0,
        "cases": root502_rows,
    })
    root230_contract_path = PACKAGE / "metadata/fresh096-root230-contract.json"
    dump(root230_contract_path, {
        "schema": "ds02.f4.fresh096.root230-contract.v1",
        "root230": root230,
        "resource_window": ref(RESOURCE),
        "strict_dispatch_sha256": STRICT_SHA,
        "cpu_threads": 2,
        "omp_threads": 2,
        "native_recipe": {"dp_m": 0.01, "time_max_s": 1.2, "time_out_s": 0.001, "native_frame_count": 1201, "solver_options": ["-tmax:1.2", "-tout:0.001"], "no_mdbc": True, "no_forcing": True},
        "uuid_policy": "Root resolves a live UUID lease at enable time and protects foreign processes; source selects no UUID",
        "source_only": True,
    })
    post_native_path = PACKAGE / "metadata/fresh096-post-native-fresh094-contract.json"
    dump(post_native_path, {
        "schema": "ds02.f4.fresh096.post-native-fresh094-contract.v1",
        "contract": fresh094_ref,
        "required_phase": "after matching full1201 native receipt; never a pre-solver native gate",
        "checks": ["saved native frame-0 vertical velocity against XML declaration", "native frame-0 input closure", "do not rescale mass", "preserve Root470/471 strict diagnostics"],
        "pass": None,
        "report_sha256": None,
        "arrays_read_by_source": False,
        "source_only": True,
    })
    stage_contract_path = PACKAGE / "metadata/fresh096-stage-contract.json"
    dump(stage_contract_path, {
        "schema": "ds02.f4.fresh096.stage-contract.v1",
        "family_id": "F4",
        "scope_id": SCOPE_ID,
        "case_count": 24,
        "upstream": {
            "fresh095": ref(FRESH095_STAGE),
            "root502_actual_basicQA": ref(root502_evidence_path),
            "root503_controller": root503_ref,
            "root504_review": root504_ref,
        },
        "native_gate": "matching Root502 actual basic QA completed/0 and report.audit.pass=true for this case",
        "native_gate_is_independent_of": ["Root500 failed attempt", "Root501 first-case/held attempt", "fresh094 post-native audit", "Root471 strict continuum/lattice diagnostic"],
        "native_solver": {"status": "future_disabled", "frames": 1201, "window_s": 1.2, "save_interval_s": 0.001, "cpu_threads": 2, "omp_threads": 2},
        "post_native": {"contract": fresh094_ref, "status": "future", "frame0_velocity_pass": None},
        "future_hashes_null": True,
        "arrays_read_or_hashed_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write": False,
        "claim_boundary": "Actual Root502 basic GenCase QA is bound; full native, frame-0 velocity, typed, visual, precision, Q-N, production remain unclaimed.",
    })

    common_static = [
        FRESH095_PLAN, FRESH095_STAGE, FRESH095_READER, FRESH095_EVIDENCE, FRESH095_WORKER,
        root502_evidence_path, root230_contract_path, stage_contract_path, post_native_path,
        ROOT503, ROOT504, ROOT230_ENTRY, ROOT230_HOME, ROOT230_CONTRACT, ROOT230_GPU,
        RUNTIME, STRICT, RESOURCE, SOLVER,
    ]
    request_rows: list[dict[str, Any]] = []
    native_plan_rows: list[dict[str, Any]] = []
    physical_conditions: set[tuple[Any, ...]] = set()
    for case_id in sorted(sources):
        src = sources[case_id]
        binding = bindings[case_id]
        qa = qa_rows[case_id]
        plan_row = src["plan"]
        owner = src["owner"]
        expected = plan_row["expected_counts"]
        actual = root502_summary(case_id, qa)
        actual_counts = actual["actual_counts"]
        if actual_counts["total"] != expected["total_particles"] or actual_counts["fixed"] != expected["fixed_particles"] or actual_counts["fluid"] != expected["fluid_particles"] or actual_counts["dimension"] != 3 or actual_counts["data2d"] is not False:
            raise ValueError(f"Root502/fresh095 count closure drift: {case_id}")
        physical_conditions.add((expected["parameters"]["gap_m"], expected["parameters"]["x_offset_m"], expected["parameters"]["y_offset_m"], expected["parameters"]["speed_m_per_s"]))
        prefix = src["xml_path"].with_suffix("")
        gencase_attempt = binding["gencase_receipt"]["attempt_id"]
        root502_attempt = qa["request"].get("attempt_id")
        native_attempt = f"root-stage1-f4-{case_id.lower()}-full1201-native-root230-fresh096-root502qa"
        manifest_path = PACKAGE / "manifests" / f"{case_id}.json"
        manifest_entries = []
        manifest_sources = [
            ("fresh095_plan", FRESH095_PLAN, sha(FRESH095_PLAN)),
            ("fresh095_stage_contract", FRESH095_STAGE, sha(FRESH095_STAGE)),
            ("fresh095_reader_contract", FRESH095_READER, sha(FRESH095_READER)),
            ("fresh095_worker", FRESH095_WORKER, sha(FRESH095_WORKER)),
            ("fresh095_binding", src["binding_path"], sha(src["binding_path"])),
            ("source_owner", src["owner_path"], src["owner_sha256"]),
            ("source_definition", src["definition_path"], src["definition_sha256"]),
            ("gencase_receipt", src["receipt_path"], src["receipt_sha256"]),
            ("prepared_xml", src["xml_path"], src["xml_sha256"]),
            ("root502_request", qa["request_path"], sha(qa["request_path"])),
            ("root502_binding", qa["binding_path"], sha(qa["binding_path"])),
            ("root502_execution_receipt", qa["receipt_path"], sha(qa["receipt_path"])),
            ("root502_basicqa_report", qa["report_path"], sha(qa["report_path"])),
            ("root503_controller", ROOT503, sha(ROOT503)),
            ("root504_review", ROOT504, sha(ROOT504)),
            ("root230_entry", ROOT230_ENTRY, sha(ROOT230_ENTRY)),
            ("root230_home_policy", ROOT230_HOME, sha(ROOT230_HOME)),
            ("root230_gpu_policy", ROOT230_GPU, sha(ROOT230_GPU)),
            ("root230_contract", ROOT230_CONTRACT, sha(ROOT230_CONTRACT)),
            ("runtime_v2", RUNTIME, sha(RUNTIME)),
            ("strict_dispatch", STRICT, sha(STRICT)),
            ("resource_window", RESOURCE, sha(RESOURCE)),
            ("solver_binary", SOLVER, sha(SOLVER)),
            ("fresh096_root230_contract", root230_contract_path, sha(root230_contract_path)),
            ("fresh096_stage_contract", stage_contract_path, sha(stage_contract_path)),
            ("fresh096_post_native_contract", post_native_path, sha(post_native_path)),
            ("fresh096_case_manifest", manifest_path, None),
        ]
        for role, path, digest in manifest_sources:
            manifest_entries.append({"role": role, "path": str(Path(path).resolve()), "expected_sha256": digest, "required": True, "read_by_source": role not in {"solver_binary"}, "science_payload": False})
        manifest_entries.append({"role": "generated_bi4_deferred", "path": str(src["bi4_path"]), "expected_sha256": None, "producer_sha256": src["bi4_sha256"], "required": True, "read_by_source": False, "deferred_to_root_solver": True, "science_payload": True})
        dump(manifest_path, {
            "schema": "ds02.f4.fresh096.native-input-manifest.v1",
            "scope_id": SCOPE_ID,
            "family_id": "F4",
            "case_id": case_id,
            "entries": manifest_entries,
            "fresh095_actual_gencase": {"status": "completed/0", "total": expected["total_particles"], "fixed": expected["fixed_particles"], "fluid": expected["fluid_particles"], "dimension": 3, "data2d": False},
            "root502_basicQA": {"status": "completed/0", "pass": True, "report": ref(qa["report_path"]), "raw_mk_type_observed": False},
            "deferred_native": True,
            "deferred_frame0_velocity": True,
            "arrays_read_or_hashed_by_source": False,
            "jobs_started_by_source": False,
            "claim_boundary": "Static native input provenance only; Root enablement and native evidence remain future.",
        })
        input_paths = unique(common_static + [src["binding_path"], src["owner_path"], src["definition_path"], src["receipt_path"], src["xml_path"], qa["request_path"], qa["binding_path"], qa["receipt_path"], qa["report_path"], manifest_path])
        input_sha256 = {str(path): sha(path) for path in input_paths}
        request = {
            "schema": "ds02.runner-request.v2",
            "family_id": "F4",
            "scope_id": SCOPE_ID,
            "case_id": case_id,
            "attempt_id": native_attempt,
            "kind": "qualification",
            "cpu_task_kind": "native_solver",
            "command": [str(SOLVER), str(prefix), "{attempt_root}/solver_output", "-tmax:1.2", "-tout:0.001"],
            "cwd": str(prefix.parent),
            "worktree_root": str(WORKTREE),
            "max_wall_seconds": 14400,
            "cpu_threads": 2,
            "estimated_peak_gpu_mib": 8192,
            "estimated_storage_bytes": 214748364800,
            "depends_on_attempts": [gencase_attempt, root502_attempt],
            "launch": False,
            "launch_allowed": False,
            "execution_allowed": False,
            "disabled": True,
            "launch_owner": "root",
            "root_only": True,
            "root_review_required": True,
            "source_only": True,
            "status": "source_only_disabled",
            "independent_case_count_increment": 0,
            "disabled_reason": "Enable only after the matching Root502 derived basic-QA receipt is completed/0 with report.audit.pass=true and all basic checks true. Root500/501 failures are preserved historical evidence and cannot substitute. Fresh094 is post-native only and is not a pre-solver dependency. Root must resolve a live non-foreign UUID lease through Root230 at enable time.",
            "input_files": [str(path) for path in input_paths],
            "input_sha256": input_sha256,
            "deferred_input_files": [str(src["xml_path"]), str(src["bi4_path"])],
            "deferred_input_sha256": {str(src["xml_path"]): src["xml_sha256"], str(src["bi4_path"]): None},
            "deferred_bi4_producer_sha256": {str(src["bi4_path"]): src["bi4_sha256"]},
            "gencase_receipt": str(src["receipt_path"]),
            "gencase_receipt_sha256": src["receipt_sha256"],
            "gencase_actual_evidence": {
                "per_case_receipt": str(src["receipt_path"]),
                "per_case_receipt_sha256": src["receipt_sha256"],
                "prepared_xml": {"path": str(src["xml_path"]), "sha256": src["xml_sha256"]},
                "prepared_report": {"path": str(src["report_path"]), "sha256": src["report_sha256"]},
                "generated_bi4": {"path": str(src["bi4_path"]), "producer_sha256": src["bi4_sha256"], "content_rehashed_by_source": False},
                "total_particles": expected["total_particles"],
                "fixed_particles": expected["fixed_particles"],
                "fluid_particles": expected["fluid_particles"],
                "moving_particles": 0,
                "floating_particles": 0,
                "solver_dimension_from_gencase": 3,
                "data2d": False,
                "raw_receipt_immutable": True,
            },
            "physical_case_id": binding["physical_case_id"],
            "physical_condition_sha256": binding["physical_condition_sha256"],
            "source_plan_condition_sha256": binding["source_plan_condition_sha256"],
            "physical_binding": {"path": str(src["owner_path"]), "sha256": src["owner_sha256"]},
            "source_definition": {"path": str(src["definition_path"]), "sha256": src["definition_sha256"]},
            "native_initial_qa": {
                "provider": "Root502-derived basic GenCase initial QA",
                "status": "completed_pass",
                "pass": True,
                "required": True,
                "request": ref(qa["request_path"]),
                "binding": ref(qa["binding_path"]),
                "execution_receipt": ref(qa["receipt_path"]),
                "report": ref(qa["report_path"]),
                "controller": root503_ref,
                "review": root504_ref,
                "attempt_id": root502_attempt,
                "actual_counts": actual_counts,
                "checks_all_true": True,
                "raw_mk_type_observed": False,
                "source_type_partition": "XML+UID derived; raw Mk/Type not claimed",
                "mass_rescaled": False,
                "strict_root471_is_not_substitute": True,
                "old500_old501_not_substitute": True,
            },
            "frame0_velocity_audit": {
                "status": "future_required_after_native_solver",
                "pass": None,
                "report": None,
                "report_sha256": None,
                "arrays_read_by_source": False,
                "post_native_contract": fresh094_ref,
                "expected_initial_velocity_from_owner": owner.get("initial_state", {}).get("velocities_m_per_s"),
            },
            "solver_recipe": {
                "dp_m": 0.01,
                "time_max_s": 1.2,
                "time_out_s": 0.001,
                "native_frame_count": 1201,
                "solver_options": ["-tmax:1.2", "-tout:0.001"],
                "no_mdbc": True,
                "no_forcing": True,
                "native_types": {"fixed": [0], "moving": [], "floating": [], "fluid": [3]},
            },
            "qualification_scope": {
                "recipe_id": "F4_finite_drop_pool_native_dbc_verlet_wendland_v1",
                "resolution": "native_dp010",
                "expected_frames": 1201,
                "time_window_s": 1.2,
                "output_interval_s": 0.001,
                "mechanism_id": owner.get("mechanism_id"),
                "status": "disabled_pending_root_enablement_and_post_native_frame0_audit",
            },
            "root230": root230,
            "root_actual_launch_source": str(ROOT230_ENTRY),
            "root_gpu_selection_profile": ROOT230_PROFILE,
            "root_solver_concurrency_cap": 8,
            "root_inventory_policy_source": str(ROOT230_HOME),
            "root_inventory_policy_source_sha256": ROOT230_HOME_SHA,
            "root_dataset_inventory_profile": ROOT230_DATASET_PROFILE,
            "root_home_free_gib_floor": 500,
            "root_nvme_free_gib_floor": 100,
            "root_nvme_peak_gib": 24,
            "root_effective_reservation_function_sha256": ROOT230_EFFECTIVE_RESERVATION_SHA,
            "resource_contract": {
                "native_concurrency": 8,
                "conversion_concurrency": 2,
                "cpu_threads": 2,
                "omp_threads": 2,
                "home_free_gib_floor": 500,
                "nvme_free_gib_floor": 100,
                "nvme_peak_gib": 24,
                "parent_budget_gpu_hours": 512,
                "parent_budget_cpu_core_hours": 3840,
                "qualification_slots": 1024,
                "production_slots": 720,
                "resource_window_approval": str(RESOURCE),
                "deadline": resource.get("deadline_utc", resource.get("deadline")),
                "foreign_gpu_processes_protected": True,
            },
            "expected_outputs": {
                "output_root": "{attempt_root}",
                "data_root": "{attempt_root}/solver_output/data",
                "execution_receipt": "{attempt_root}/execution-receipt.json",
                "execution_receipt_sha256": None,
                "full_native_frames": 1201,
                "frame0_velocity_audit": None,
                "typed_receipt": None,
                "all_future_sha256": None,
            },
            "arrays_read_by_source": False,
            "bi4_read_by_source": False,
            "no_jobs_started_by_source": True,
            "no_shared_registry_write": True,
            "read_policy": {"source_arrays": False, "native_bi4": "deferred Root230 solver input", "csv": False, "dat": False, "h5": False, "typed": "future after native and frame0 audit"},
            "q_n_status": "not_assessed",
            "precision_status": "not_accepted",
            "production_approval": "none",
            "root470_root471_strict_diagnostic": "preserved separately; no promotion or relabeling",
            "claim_boundary": "Root502 basic GenCase QA is actual and complete for this case. Full 1201-frame native solver, post-native fresh094 frame-0 velocity, typed conversion, visual, precision, Q-N, production and independent-case credit remain future.",
        }
        request_path = PACKAGE / "requests" / f"{case_id}-full1201-native-root230-fresh096-disabled.request.json"
        dump(request_path, request)
        request_rows.append({"case_id": case_id, "request": ref(request_path), "manifest": ref(manifest_path), "root502_basicQA": actual, "native_status": "future_disabled", "future_native_receipt_sha256": None, "future_frame0_sha256": None})
        native_plan_rows.append({"case_id": case_id, "attempt_id": native_attempt, "gencase_attempt_id": gencase_attempt, "root502_basicqa_attempt_id": root502_attempt, "root502_basicqa_pass": True, "native_receipt": None, "frame0_velocity_report": None, "physical_condition_sha256": binding["physical_condition_sha256"], "status": "future_disabled_until_root_enablement_then_post_native_fresh094", "independent_case_count_increment": 0})

    if len(physical_conditions) != 24:
        raise ValueError("F4 physical conditions are not 24 distinct tuples")
    native_plan_path = PACKAGE / "metadata/fresh096-native-plan.json"
    dump(native_plan_path, {
        "schema": "ds02.f4.fresh096.native-plan.v1",
        "scope_id": SCOPE_ID,
        "family_id": "F4",
        "case_count": 24,
        "root502_basicqa": {"required": True, "actual_completed0": 24, "all_pass": True, "review": root504_ref, "controller": root503_ref, "source_type_partition": "XML+UID derived", "raw_mk_type_observed": False},
        "solver_recipe": {"dp_m": 0.01, "time_max_s": 1.2, "time_out_s": 0.001, "native_frame_count": 1201, "solver_options": ["-tmax:1.2", "-tout:0.001"], "no_mdbc": True, "no_forcing": True},
        "root230": root230,
        "post_native_fresh094": {"contract": fresh094_ref, "required_after_native": True, "pass": None},
        "cases": native_plan_rows,
        "native_receipts": None,
        "frame0_velocity_reports": None,
        "typed_hashes": None,
        "all_future_hashes_null": True,
        "source_only": True,
        "claim_boundary": "Actual Root502 basic QA only; no native/typed/visual/precision/Q-N/production result.",
    })
    binding_path = PACKAGE / "metadata/fresh096-native-binding.json"
    dump(binding_path, {
        "schema": "ds02.f4.fresh096.native-binding.v1",
        "scope_id": SCOPE_ID,
        "family_id": "F4",
        "fresh095": {"plan": ref(FRESH095_PLAN), "stage": ref(FRESH095_STAGE), "reader": ref(FRESH095_READER), "source_commit": plan.get("actual_source_commit")},
        "root502": {"scope": ROOT502_SCOPE, "evidence": ref(root502_evidence_path), "controller": root503_ref, "review": root504_ref, "actual_basicQA_completed0": 24, "all_checks_true": True, "decoder_alias_repair_preserved": True},
        "root230": root230,
        "fresh094": {"contract": fresh094_ref, "post_native_only": True},
        "actual_counts": {"total": 83233, "fixed": 24161, "fluid": 59072, "moving": 0, "floating": 0, "dimension": 3},
        "native_request_count": 24,
        "actual_native_receipts": None,
        "actual_frame0_reports": None,
        "typed_hashes": None,
        "independent_case_count_increment": 0,
        "claim_boundary": "Source-only disabled native handoff after actual Root502 basic QA; no solver or post-native claim.",
    })
    request_index_path = PACKAGE / "evidence/request-index.json"
    dump(request_index_path, {
        "schema": "ds02.f4.fresh096.request-index.v1",
        "scope_id": SCOPE_ID,
        "family_id": "F4",
        "case_count": 24,
        "rows": request_rows,
        "launch_allowed": False,
        "all_requests_disabled": True,
        "root502_basicqa_actual_completed0": 24,
        "native_receipts": None,
        "frame0_reports": None,
        "typed_hashes": None,
        "all_future_hashes_null": True,
        "arrays_read_or_hashed_by_source": False,
        "jobs_started_by_source": False,
        "root500_root501_failures_preserved": True,
        "fresh094_post_native_only": True,
    })
    closure_paths = unique(common_static + [root502_evidence_path, root230_contract_path, stage_contract_path, post_native_path, native_plan_path, binding_path, request_index_path, FRESH094_MANIFEST])
    for case_id in sorted(sources):
        src = sources[case_id]
        qa = qa_rows[case_id]
        closure_paths.extend([src["binding_path"], src["owner_path"], src["definition_path"], src["receipt_path"], src["xml_path"], qa["request_path"], qa["binding_path"], qa["receipt_path"], qa["report_path"], PACKAGE / "manifests" / f"{case_id}.json", PACKAGE / "requests" / f"{case_id}-full1201-native-root230-fresh096-disabled.request.json"])
    closure_path = PACKAGE / "evidence/source-static-closure.json"
    closure_paths = unique(closure_paths)
    dump(closure_path, {
        "schema": "ds02.f4.fresh096.source-static-closure.v1",
        "files": {str(path): sha(path) for path in closure_paths},
        "scientific_payloads": [],
        "deferred_scientific_payloads": {"bi4_producer_attestations": 24, "bi4_content_read_or_hashed_by_source": False},
        "root502_actual_basicqa_reports_bound": 24,
        "root230_native_receipts_bound": 0,
        "root230_frame0_reports_bound": 0,
        "shared_registry_write": False,
        "jobs_started": 0,
    })
    dump(PACKAGE / "F4_STAGE1_FRESH096_ROOT502_BASICQA_TO_ROOT230_NATIVE_BIND_MANIFEST.json", {
        "schema": "ds02.f4.fresh096.manifest.v1",
        "scope_id": SCOPE_ID,
        "family_id": "F4",
        "case_count": 24,
        "actual_gencase_completed0": 24,
        "actual_root502_basicQA_completed0": 24,
        "all_basic_checks_true": True,
        "native_requests": 24,
        "all_requests_disabled": True,
        "future_hashes": None,
        "fresh094": {"post_native_only": True, "manifest": fresh094_ref},
        "root500_root501_failures_preserved": True,
        "root471_strict_negative_preserved": True,
        "source_only": True,
        "independent_case_count_increment": 0,
        "claim_boundary": "Actual Root502 basic QA is bound. Full native 1201 frames, frame0 velocity, typed, visual, precision, Q-N and production outcomes remain future.",
    })
    (PACKAGE / "README.md").write_text(
        """# F4 fresh096 Root502 basic QA to Root230 full1201 native handoff

Fresh096 binds the actual Root502-derived basic GenCase QA closure for all 24
F4 cases. Root503 reports 24/24 completed/0 and Root504 records all basic
checks true. The original Root500 first-case failure/held evidence and Root471
strict continuum/lattice negative evidence remain preserved.

Each native request is disabled and gated on its matching Root502 request,
actual execution receipt, and `gencase-basic-initial-qa.json` report. The gate
requires completed/0 plus `audit.pass=true` and every basic check true. Raw
Mk/Type are not claimed as observed: the type/source partition remains
derived from XML and Idp ranges. Mass is diagnostic only and is never
rescaled.

The native command is the approved Root230 solver with the exact
`-tmax:1.2 -tout:0.001` recipe, dp=.01, 1,201 frames, no mDBC and no forcing.
CPU/OMP threads are 2. Root resolves live UUID leases only at enable time,
protects foreign processes, and enforces the Home/NVMe floors and parent
resource window. Future native receipts, frame-0 reports, typed outputs and
hashes are null.

Fresh094 is recorded as a post-native frame-0 downward-velocity contract only;
it is deliberately absent from the pre-solver dependency list so the
pipeline is acyclic. No solver, converter, array read, scientific-payload
hash/copy, or shared registry write was performed by this package.

Validate with:
`PYTHONPYCACHEPREFIX=/tmp/ds02-fresh096-validator-pyc python3 tests/validate_source_contract.py`.
""",
        encoding="utf-8",
    )
    return {"schema": "ds02.f4.fresh096.build-result.v1", "package": str(PACKAGE), "actual_root502_basicqa_completed0": 24, "native_requests": 24, "all_requests_disabled": True, "future_hashes_null": True, "source_only": True, "bi4_read_or_hashed_by_source": False}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
