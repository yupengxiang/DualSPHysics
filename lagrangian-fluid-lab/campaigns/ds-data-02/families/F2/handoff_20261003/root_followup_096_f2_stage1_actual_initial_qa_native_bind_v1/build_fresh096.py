#!/usr/bin/env python3
"""Build the F2 fresh096 actual-GenCase-bound QA/native handoff.

This builder consumes compact JSON/XML/source metadata only.  It never opens
BI4/VTK/CSV/H5 data and never starts GenCase, PartVTK, DualSPHysics, or a
shared runner.  Root270's producer hashes for the generated binary are copied
from its prepared-input-report; this process does not rehash that binary.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping


F2_WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
F2_LAB = F2_WORKTREE / "lagrangian-fluid-lab"
LAB = INTEGRATION / "lagrangian-fluid-lab"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2")
BASE095 = F2_LAB / "campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_095_f2_stage1_first8_offset_lattice_v1"
HERE = F2_LAB / "campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_096_f2_stage1_actual_initial_qa_native_bind_v1"
ROOT270 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f2_first8_five_gencase_dispatch_closure_270"
ROOT269 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f2_first8_five_distinct_genuine_gencase_269"
DISPATCH_REPAIR = ROOT270 / "root-dispatch-preflight-repair.json"
ROOT142 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT230_LAUNCH = ROOT230 / "launch.py"
ROOT230_HOME = ROOT230 / "root_native_home_floor_inventory_policy.py"
ROOT230_SOURCE = ROOT230 / "source-policy-contract.json"
GPU_POLICY = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
RESOURCE_APPROVAL = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
STRICT = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
PARTVTK = F2_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
# Qualification/production requests are executed by the shared Root runner
# against the canonical base-lab solver, as required by runtime_v2.  Keep this
# executable outside the F2 worktree and digest-bind it like the other
# non-science runtime inputs.
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
PYTHON = Path("/usr/bin/python3.10")
if not PYTHON.is_file():
    PYTHON = F2_LAB / ".venv/bin/python"
QA_TEMPLATE = F2_LAB / "campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_091_f2_stage1_actual_initial_qa_v1/workers/f2_stage1_initial_qa_worker_v2.py"
SCHEMA = "ds02.f2.stage1.fresh096.actual-gencase-bound-qa-native.v1"
SCOPE = "F2_STAGE1_FIRST8_OFFSET_LATTICE_V1"
CASE_IDS = (
    "F2_STAGE1_FIRST8_OFFSET_RX047_DP010_SPATIAL_REFERENCE_SAVE010",
    "F2_STAGE1_FIRST8_OFFSET_RX050_DP010_SPATIAL_REFERENCE_SAVE010",
    "F2_STAGE1_FIRST8_OFFSET_RX055_DP010_SPATIAL_REFERENCE_SAVE010",
    "F2_STAGE1_FIRST8_OFFSET_RX060_DP010_SPATIAL_REFERENCE_SAVE010",
    "F2_STAGE1_FIRST8_OFFSET_RX063_DP010_SPATIAL_REFERENCE_SAVE010",
)


def sha256(path: Path) -> str:
    """Hash metadata/source files only; binary scientific inputs are forbidden."""
    path = Path(path).resolve()
    if path.suffix.lower() in {".bi4", ".vtk", ".csv", ".h5", ".hdf5", ".gif"}:
        raise AssertionError(f"scientific array/artifact hashing is forbidden in source builder: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Mapping[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require_file(path: Path) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def binding(path: Path, known_sha: str | None = None, *, science: bool = False) -> dict[str, Any]:
    path = require_file(path)
    value: dict[str, Any] = {"path": str(path), "sha256": known_sha or sha256(path)}
    if science:
        value["hash_provenance"] = "Root270 prepared-input-report producer hash; fresh096 does not open or rehash this artifact"
    return value


def read_base_rows() -> dict[str, Mapping[str, Any]]:
    manifest = load(BASE095 / "F2_STAGE1_FIRST8_REMAINING_OFFSET_LATTICE_MANIFEST.json")
    rows = {str(row["case_id"]): row for row in manifest["cases"]}
    if set(rows) != set(CASE_IDS):
        raise AssertionError(f"fresh095 cases differ: {sorted(rows)}")
    return rows


def expected_guard_hashes() -> dict[str, str]:
    repair = load(DISPATCH_REPAIR)
    guards = repair.get("guard_hashes")
    if not isinstance(guards, Mapping):
        raise AssertionError("Root270 dispatch repair has no guard_hashes")
    result = {str(k): str(v) for k, v in guards.items()}
    expected_paths = {str(RUNTIME.resolve()), str(STRICT.resolve()), str(ROOT142.resolve()), str(RESOURCE_APPROVAL.resolve())}
    if set(result) != expected_paths:
        raise AssertionError(f"Root270 guard set differs: {sorted(result)}")
    for path, expected in result.items():
        if sha256(Path(path)) != expected:
            raise AssertionError(f"guard digest drift: {path}")
    return result


def root270_request(case_id: str) -> tuple[Path, Mapping[str, Any]]:
    path = require_file(ROOT270 / f"{case_id}-gencase-request.json")
    request = load(path)
    if request.get("case_id") != case_id or request.get("scope_id") != SCOPE:
        raise AssertionError(f"Root270 request identity mismatch: {path}")
    if request.get("launch_owner") != "root" or request.get("status") != "root_enabled_distinct_source_actual_gen_pending":
        raise AssertionError(f"unexpected Root270 request state: {path}")
    if not all(request.get(k) is True for k in ("launch", "launch_allowed", "execution_allowed")):
        raise AssertionError(f"Root270 request was not the actual enabled request: {path}")
    return path, request


def root269_request(case_id: str) -> Path:
    return require_file(ROOT269 / f"{case_id}-gencase-request.json")


def actual_case(case_id: str, base_row: Mapping[str, Any], guard_hashes: Mapping[str, str]) -> dict[str, Any]:
    request_path, request = root270_request(case_id)
    attempt_id = str(request["attempt_id"])
    attempt_root = (DATA_ROOT / case_id / attempt_id).resolve()
    if not attempt_root.is_dir():
        raise FileNotFoundError(attempt_root)
    receipt_path = require_file(attempt_root / "execution-receipt.json")
    report_path = require_file(attempt_root / "prepared/prepared-input-report.json")
    receipt = load(receipt_path)
    report = load(report_path)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise AssertionError(f"Root270 receipt is not completed/0: {receipt_path}")
    if receipt.get("request_sha256") != sha256(request_path):
        raise AssertionError(f"receipt/request digest mismatch: {case_id}")
    if receipt.get("solver_dimension_from_gencase") != 3:
        raise AssertionError(f"Root270 output is not genuine 3-D: {case_id}")
    if receipt.get("input_hashes_after_run") != receipt.get("input_hashes_at_launch"):
        raise AssertionError(f"Root270 input digest changed during run: {case_id}")
    if request.get("physical_condition_sha256") != base_row.get("physical_condition_sha256"):
        raise AssertionError(f"physical condition drift: {case_id}")
    if request.get("numerical_recipe_sha256") != base_row.get("numerical_recipe_sha256"):
        raise AssertionError(f"recipe drift: {case_id}")
    input_hashes = request.get("input_sha256")
    if not isinstance(input_hashes, Mapping):
        raise AssertionError(f"Root270 input digest map missing: {case_id}")
    for path, expected in guard_hashes.items():
        if input_hashes.get(path) != expected:
            raise AssertionError(f"Root270 request omitted/differed guard digest {path}: {case_id}")
    # GenCase's prefix itself is not a file; the prepared XML/BI4 are sibling files.
    prefix = Path(str(report["prefix"])).resolve()
    xml_path = require_file(prefix.with_suffix(".xml"))
    bi4_path = require_file(prefix.with_suffix(".bi4"))
    counts = report.get("generated_xml_particle_counts")
    if not isinstance(counts, Mapping):
        raise AssertionError(f"measured XML counts missing: {report_path}")
    normalized_counts = {str(k): int(v) for k, v in counts.items()}
    measured_total = int(report["actual_total_particles"])
    if measured_total != int(receipt["total_particles"]):
        raise AssertionError(f"receipt/report total mismatch: {case_id}")
    if int(receipt["fluid_particles"]) != normalized_counts.get("fluid"):
        raise AssertionError(f"receipt/report fluid mismatch: {case_id}")
    if sum(normalized_counts.values()) != measured_total:
        raise AssertionError(f"generated XML counts do not sum to measured total: {case_id}")
    source_def = require_file(Path(str(base_row["definition"]["path"])))
    source_motion = require_file(Path(str(base_row["motion"]["path"])))
    source_metadata = require_file(Path(str(base_row["metadata"]["path"])))
    source_owner = require_file(Path(str(base_row["owner"]["path"])))
    if report.get("definition_sha256") != base_row["definition"]["sha256"]:
        raise AssertionError(f"actual report source definition drift: {case_id}")
    root269_path = root269_request(case_id)
    return {
        "case_id": case_id,
        "base_row": base_row,
        "root270_request_path": request_path,
        "root270_request": request,
        "root269_request_path": root269_path,
        "root270_request_sha256": sha256(request_path),
        "root269_request_sha256": sha256(root269_path),
        "attempt_id": attempt_id,
        "attempt_root": attempt_root,
        "receipt_path": receipt_path,
        "receipt": receipt,
        "report_path": report_path,
        "report": report,
        "prefix": prefix,
        "xml_path": xml_path,
        "bi4_path": bi4_path,
        "source_def": source_def,
        "source_motion": source_motion,
        "source_metadata": source_metadata,
        "source_owner": source_owner,
        "counts": normalized_counts,
        "guard_hashes": dict(guard_hashes),
    }


def make_binding(case: Mapping[str, Any]) -> dict[str, Any]:
    receipt = case["receipt"]
    report = case["report"]
    return {
        "schema": "ds02.f2.stage1.fresh096.actual-gencase-binding.v1",
        "family_id": "F2",
        "scope_id": SCOPE,
        "case_id": case["case_id"],
        "physical_case_id": case["base_row"]["physical_case_id"],
        "physical_condition_sha256": case["base_row"]["physical_condition_sha256"],
        "numerical_recipe_sha256": case["base_row"]["numerical_recipe_sha256"],
        "source_only": True,
        "execution_allowed": False,
        "launch_allowed": False,
        "claims": {"gen_case": True, "initial_qa": False, "native_solver": False, "typed": False, "visual": False, "qualification": False, "production": False},
        "root270_dispatch": {
            "request": binding(case["root270_request_path"]),
            "request_sha256": case["root270_request_sha256"],
            "attempt_id": case["attempt_id"],
            "status": case["root270_request"].get("status"),
            "guard_hashes": case["guard_hashes"],
            "input_hashes_at_launch_equal_after_run": True,
        },
        "root270_gencase": {
            "receipt": binding(case["receipt_path"]),
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "solver_dimension_from_gencase": receipt.get("solver_dimension_from_gencase"),
            "total_particles": receipt.get("total_particles"),
            "fluid_particles": receipt.get("fluid_particles"),
            "binary_sha256": receipt.get("binary_sha256"),
            "stdout_sha256": receipt.get("stdout_sha256"),
            "output_root": receipt.get("output_root"),
        },
        "prepared_input_report": binding(case["report_path"]),
        "actual_generated_outputs": {
            "prefix": str(case["prefix"]),
            "xml": binding(case["xml_path"], known_sha=report.get("xml_sha256")),
            "bi4": binding(case["bi4_path"], known_sha=report.get("bi4_sha256"), science=True),
            "generated_xml_particle_counts": dict(case["counts"]),
            "actual_total_particles": report.get("actual_total_particles"),
            "actual_generated_constants": report.get("actual_generated_constants"),
            "producer_hashes": {"xml_sha256": report.get("xml_sha256"), "bi4_sha256": report.get("bi4_sha256"), "receipt_sha256": sha256(case["receipt_path"])},
        },
        "source_inputs": {
            "definition": binding(case["source_def"]),
            "motion": binding(case["source_motion"]),
            "metadata": binding(case["source_metadata"]),
            "source095_owner": binding(case["source_owner"]),
        },
        "count_policy": {
            "source": "Root270 receipt plus prepared-input-report generated XML summary",
            "measured_only": True,
            "no_forced_count": True,
            "no_mother_count_substitution": True,
            "mass_rescale": False,
        },
        "root269_preservation": {"request": str(case["root269_request_path"]), "request_sha256": case["root269_request_sha256"], "status": "rejected_before_registration; preserved; not consumed"},
        "future_initial_qa_report_sha256": None,
        "future_native_solver_receipt_sha256": None,
    }


def request_input_map(paths: list[Path], known: Mapping[Path, str] | None = None) -> dict[str, str]:
    known = {Path(k).resolve(): str(v) for k, v in (known or {}).items()}
    output: dict[str, str] = {}
    for path in paths:
        path = Path(path).resolve()
        if path in known:
            output[str(path)] = known[path]
        else:
            output[str(path)] = sha256(path)
    return output


def common_request(case: Mapping[str, Any], binding_path: Path, owner_path: Path, *, worker: Path) -> tuple[list[Path], dict[str, str]]:
    paths = [
        worker, case["source_def"], case["source_motion"], case["source_metadata"], case["source_owner"], binding_path,
        case["receipt_path"], case["report_path"], case["xml_path"], case["bi4_path"],
        case["root270_request_path"], case["root269_request_path"], DISPATCH_REPAIR, RUNTIME, STRICT, ROOT142,
        RESOURCE_APPROVAL, ROOT230_LAUNCH, ROOT230_HOME, ROOT230_SOURCE, GPU_POLICY, BASE095 / "F2_STAGE1_FIRST8_REMAINING_OFFSET_LATTICE_MANIFEST.json",
        owner_path, SOLVER,
    ]
    known = {case["xml_path"]: case["report"].get("xml_sha256"), case["bi4_path"]: case["report"].get("bi4_sha256")}
    return paths, request_input_map(paths, known)


def make_qa_request(case: Mapping[str, Any], binding_path: Path, owner_path: Path, worker: Path) -> dict[str, Any]:
    paths, hashes = common_request(case, binding_path, owner_path, worker=worker)
    attempt = f"root-stage1-f2-{case['case_id'].lower()}-actual-initial-qa-096"
    report = case["report"]
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F2", "scope_id": SCOPE, "case_id": case["case_id"],
        "physical_case_id": case["base_row"]["physical_case_id"], "physical_condition_sha256": case["base_row"]["physical_condition_sha256"],
        "numerical_recipe_sha256": case["base_row"]["numerical_recipe_sha256"],
        "attempt_id": attempt, "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2, "max_wall_seconds": 1800,
        "estimated_storage_bytes": 268435456, "cwd": str(F2_LAB.resolve()), "worktree_root": str(F2_WORKTREE.resolve()),
        "command": [str(PYTHON.resolve()), str(worker.resolve()), "--case-id", case["case_id"], "--definition", str(case["source_def"]), "--gencase-receipt", str(case["receipt_path"]), "--partvtk", str(PARTVTK), "--partvtk-output-dir", "{attempt_root}/partvtk", "--output", "{attempt_root}/actual-initial-qa.json"],
        "input_files": [str(path.resolve()) for path in paths], "input_sha256": hashes,
        "launch_owner": "root", "launch": False, "launch_allowed": False, "execution_allowed": False, "disabled": True,
        "source_only": True, "root_review_required": True, "production_claim": "none", "qualification_claim": "none", "numerical_precision_status": "not_accepted",
        "depends_on_attempt": case["attempt_id"],
        "gencase_receipt": str(case["receipt_path"]), "gencase_receipt_sha256": sha256(case["receipt_path"]),
        "actual_gencase_output": {"receipt": str(case["receipt_path"]), "receipt_sha256": sha256(case["receipt_path"]), "prepared_input_report": str(case["report_path"]), "prepared_input_report_sha256": sha256(case["report_path"]), "xml": str(case["xml_path"]), "xml_sha256": report.get("xml_sha256"), "bi4": str(case["bi4_path"]), "bi4_sha256": report.get("bi4_sha256"), "prefix": str(case["prefix"]), "counts": dict(case["counts"]), "actual_total_particles": report.get("actual_total_particles"), "actual_generated_constants": report.get("actual_generated_constants"), "producer_binary_sha256": case["receipt"].get("binary_sha256")},
        "count_contract": {"expected_counts": {"total_particles": None, "fixed_particles": None, "moving_particles": None, "fluid_particles": None}, "actual_count_source": "Root270 completed receipt/prepared-input-report", "no_forced_count": True, "no_mother_count_substitution": True, "mass_policy": "derive unscaled actual XML/CSV only; no rescale"},
        "required_checks": ["Root270 receipt completed and returncode 0", "actual generated XML 3-D with dp=.01, TimeMax=4, TimeOut=.01", "official PartVTK frame-zero fields finite", "dynamic Type/Mk/UID/zone partitions", "positive Type=3 fluid", "source geometry/domain/non-overlap checks", "unscaled native mass from this case only"],
        "output_contract": {"actual_counts": None, "actual_frame0_csv_sha256": None, "actual_initial_qa_report_sha256": None, "mass_rescale": False},
        "raw_output_root": str((DATA_ROOT / case["case_id"]).resolve()), "raw_output_policy": "PartVTK CSV/log remain under external DS-DATA-02 runner attempt; only bounded JSON report is consumed",
        "binding": str(binding_path.resolve()), "binding_sha256": sha256(binding_path), "owner_provenance": str(owner_path.resolve()),
        "status": "source_only_disabled_actual_root270_gencase_bound", "disabled_reason": "Root enables only after reviewing actual Root270 GenCase receipt and this closed input digest set; fresh096 runs no PartVTK",
    }


def make_solver_request(case: Mapping[str, Any], binding_path: Path, owner_path: Path, qa_path: Path, worker: Path) -> dict[str, Any]:
    paths, hashes = common_request(case, binding_path, owner_path, worker=worker)
    paths = [*paths, qa_path]
    hashes[ str(qa_path.resolve()) ] = sha256(qa_path)
    attempt = f"root-stage1-f2-{case['case_id'].lower()}-full401-native-096"
    report = case["report"]
    return {
        "schema": "ds02.runner-request.v2", "family_id": "F2", "scope_id": SCOPE, "case_id": case["case_id"],
        "physical_case_id": case["base_row"]["physical_case_id"], "physical_condition_sha256": case["base_row"]["physical_condition_sha256"], "numerical_recipe_sha256": case["base_row"]["numerical_recipe_sha256"],
        "attempt_id": attempt, "kind": "qualification", "cpu_task_kind": "solver", "cpu_threads": 2, "target_gpu_index": None, "max_wall_seconds": 3600, "estimated_peak_gpu_mib": 8192, "estimated_storage_bytes": 8589934592,
        "cwd": "{gencase_output_root}", "worktree_root": str(F2_WORKTREE.resolve()),
        "command": [str(SOLVER.resolve()), "{gencase_prefix}", "{attempt_root}/solver_output", "-tmax:4.0", "-tout:0.01"],
        "input_files": [str(path.resolve()) for path in paths], "input_sha256": hashes,
        "launch_owner": "root", "launch": False, "launch_allowed": False, "execution_allowed": False, "disabled": True, "source_only": True, "solver_launch_forbidden": True, "root_review_required": True,
        "production_claim": "none", "qualification_claim": "none", "numerical_precision_status": "not_accepted",
        "depends_on_attempts": [case["attempt_id"], f"root-stage1-f2-{case['case_id'].lower()}-actual-initial-qa-096"],
        "gencase_attempt_id": case["attempt_id"], "gencase_receipt": str(case["receipt_path"]), "gencase_receipt_sha256": sha256(case["receipt_path"]), "gencase_prefix": str(case["prefix"]), "gencase_output_root": str(case["prefix"].parent),
        "prepared_input_report": str(case["report_path"]), "prepared_input_report_sha256": sha256(case["report_path"]), "generated_xml": str(case["xml_path"]), "generated_xml_sha256": report.get("xml_sha256"), "generated_bi4": str(case["bi4_path"]), "generated_bi4_sha256": report.get("bi4_sha256"), "actual_particle_counts": dict(case["counts"]), "actual_total_particles": report.get("actual_total_particles"),
        "initial_qa_request": str(qa_path.resolve()), "initial_qa_request_sha256": sha256(qa_path), "initial_qa_report": "{qa_attempt_root}/actual-initial-qa.json", "initial_qa_report_sha256": None, "native_initial_qa_required": True,
        "expected_output": {"full_window_s": 4.0, "save_interval_s": 0.01, "frame_count": 401, "solver_dimension": 3, "native_output_hash": None, "actual_frame_count": None, "actual_particle_counts": None, "execution_receipt_sha256": None, "run_out_sha256": None},
        "solver_options_policy": "exact Root230 native command only; no mdbc/noslip addition; generated XML mvrotfile authoritative",
        "root_dataset_inventory_profile": "root_home_floor_no_legacy_dataset_walk_native_v1", "root_inventory_policy_source_sha256": sha256(ROOT230_HOME),
        "root230_dispatch": {"entry": str(ROOT230_LAUNCH.resolve()), "entry_sha256": sha256(ROOT230_LAUNCH), "home_floor_policy": str(ROOT230_HOME.resolve()), "home_floor_policy_sha256": sha256(ROOT230_HOME), "source_policy_contract": str(ROOT230_SOURCE.resolve()), "source_policy_contract_sha256": sha256(ROOT230_SOURCE), "gpu_policy": str(GPU_POLICY.resolve()), "gpu_policy_sha256": sha256(GPU_POLICY), "resource_window": str(RESOURCE_APPROVAL.resolve()), "resource_window_sha256": sha256(RESOURCE_APPROVAL), "profile": "root_home_floor_no_legacy_dataset_walk_native_v1", "root_owned": True},
        "native_solver_provenance": {"source": "actual Root270 GenCase output; native solver remains future", "motion_cwd": str(case["prefix"].parent), "actual_gencase_receipt": str(case["receipt_path"]), "actual_gencase_receipt_sha256": sha256(case["receipt_path"]), "future_solver_receipt_sha256": None, "future_native_output_hash": None},
        "raw_output_root": str((DATA_ROOT / case["case_id"]).resolve()), "binding": str(binding_path.resolve()), "binding_sha256": sha256(binding_path), "owner_provenance": str(owner_path.resolve()),
        "status": "source_only_disabled_actual_root270_gencase_bound_pending_initial_qa", "disabled_reason": "Root230 may enable only after this case's actual initial QA report is completed/pass; fresh096 starts no solver",
    }


def make_owner(case: Mapping[str, Any], binding_path: Path, qa_path: Path, solver_path: Path) -> dict[str, Any]:
    base_owner = load(case["source_owner"])
    return {
        "schema": "ds02.f2.stage1.fresh096.actual-gencase-bound-owner.v1", "family_id": "F2", "scope_id": SCOPE,
        "case_id": case["case_id"], "physical_case_id": case["base_row"]["physical_case_id"], "physical_condition_sha256": case["base_row"]["physical_condition_sha256"], "numerical_recipe_sha256": case["base_row"]["numerical_recipe_sha256"],
        "canonical_identity": base_owner.get("canonical_identity"), "source095_owner": binding(case["source_owner"]),
        "execution_owner": {"actor": "root", "root270_request": binding(case["root270_request_path"]), "actual_receipt": binding(case["receipt_path"]), "receipt_status": case["receipt"].get("status"), "receipt_returncode": case["receipt"].get("returncode"), "root270_request_sha256": case["root270_request_sha256"]},
        "actual_gencase_provenance": {"prepared_input_report": binding(case["report_path"]), "xml": binding(case["xml_path"], known_sha=case["report"].get("xml_sha256")), "bi4": binding(case["bi4_path"], known_sha=case["report"].get("bi4_sha256"), science=True), "counts": dict(case["counts"]), "total_particles": case["report"].get("actual_total_particles"), "fluid_particles": case["receipt"].get("fluid_particles"), "producer_binary_sha256": case["receipt"].get("binary_sha256")},
        "typed_scope_provenance": {"state": "pending_actual_initial_qa_native_full401_and_root_visual", "typed_product_status": "not_produced", "initial_qa_request": str(qa_path.resolve()), "initial_qa_request_sha256": None, "initial_qa_report_sha256": None, "solver_request": str(solver_path.resolve()), "solver_request_sha256": None, "native_receipt_sha256": None, "visual_acceptance": None, "qualification": "none", "production_approval": "none"},
        "independent_case_count_increment": 0, "mass_policy": "measured Root270 XML/report counts are recorded; native mass/QA is future and unscaled; no mother substitution", "execution_allowed": False, "source_only": True,
        "root269_preservation": {"request": str(case["root269_request_path"]), "request_sha256": case["root269_request_sha256"], "status": "rejected_before_registration; preserved"},
        "claims": {"initial_qa": False, "native_solver": False, "typed": False, "visual": False, "qualification": False, "production": False},
        "actual_evidence": {"gencase": str(case["receipt_path"]), "gencase_receipt_sha256": sha256(case["receipt_path"]), "initial_qa": None, "native_solver": None, "visual_acceptance": None},
        "disabled_requests": {"actual_qa": str(qa_path.resolve()), "solver": str(solver_path.resolve()), "binding": str(binding_path.resolve())},
    }


def build() -> None:
    guard_hashes = expected_guard_hashes()
    base_rows = read_base_rows()
    cases = [actual_case(cid, base_rows[cid], guard_hashes) for cid in CASE_IDS]
    for name in ("source", "requests", "owners", "bindings", "evidence", "workers"):
        (HERE / name).mkdir(parents=True, exist_ok=True)
    worker = HERE / "workers/f2_stage1_initial_qa_worker_v2.py"
    shutil.copyfile(QA_TEMPLATE, worker)
    binding_paths: dict[str, Path] = {}
    for case in cases:
        path = HERE / "bindings" / f"{case['case_id']}.actual-gencase-binding.json"
        dump(path, make_binding(case)); binding_paths[case["case_id"]] = path
    # Create owners before requests so each disabled request can digest-bind its
    # owner provenance without a request<->owner hash cycle.  The request files
    # themselves carry their closed hashes in the manifest.
    qa_paths: dict[str, Path] = {}; solver_paths: dict[str, Path] = {}
    for case in cases:
        cid = case["case_id"]
        qa_paths[cid] = HERE / "requests" / f"{cid}-actual-initial-qa-disabled.json"
        solver_paths[cid] = HERE / "requests" / f"{cid}-full401-native-disabled.json"
    owner_paths: dict[str, Path] = {}
    for case in cases:
        cid = case["case_id"]
        path = HERE / "owners" / f"{cid}.actual-gencase-bound.owner.json"
        dump(path, make_owner(case, binding_paths[cid], qa_paths[cid], solver_paths[cid])); owner_paths[cid] = path
    for case in cases:
        cid = case["case_id"]
        dump(qa_paths[cid], make_qa_request(case, binding_paths[cid], owner_paths[cid], worker))
        dump(solver_paths[cid], make_solver_request(case, binding_paths[cid], owner_paths[cid], qa_paths[cid], worker))
    rows = []
    for case in cases:
        cid = case["case_id"]; report = case["report"]
        rows.append({
            "case_id": cid, "physical_case_id": case["base_row"]["physical_case_id"], "physical_condition_sha256": case["base_row"]["physical_condition_sha256"], "numerical_recipe_sha256": case["base_row"]["numerical_recipe_sha256"],
            "root270_attempt_id": case["attempt_id"], "root270_request": binding(case["root270_request_path"]), "root270_receipt": binding(case["receipt_path"]), "prepared_input_report": binding(case["report_path"]),
            "actual_prefix": str(case["prefix"]), "actual_xml": binding(case["xml_path"], known_sha=report.get("xml_sha256")), "actual_bi4": binding(case["bi4_path"], known_sha=report.get("bi4_sha256"), science=True),
            "generated_xml_particle_counts": dict(case["counts"]), "actual_total_particles": report.get("actual_total_particles"), "actual_fluid_particles": case["receipt"].get("fluid_particles"), "actual_solver_dimension": case["receipt"].get("solver_dimension_from_gencase"),
            "producer_hashes": {"request_sha256": case["root270_request_sha256"], "receipt_sha256": sha256(case["receipt_path"]), "prepared_input_report_sha256": sha256(case["report_path"]), "xml_sha256": report.get("xml_sha256"), "bi4_sha256": report.get("bi4_sha256"), "binary_sha256": case["receipt"].get("binary_sha256")},
            "binding": binding(binding_paths[cid]), "owner": binding(owner_paths[cid]), "actual_qa_request": binding(qa_paths[cid]), "solver_request": binding(solver_paths[cid]),
            "future_initial_qa_report_sha256": None, "future_native_receipt_sha256": None, "typed_scope_status": "pending", "claims": {"qualification": False, "production": False, "visual": False},
        })
    dump(HERE / "evidence/root270-actual-gencase-audit.json", {"schema": "ds02.f2.stage1.fresh096.root270-actual-gencase-audit.v1", "source_only": True, "arrays_opened": False, "guard_hashes": guard_hashes, "cases": rows, "all_receipts_completed0": True, "no_initial_qa_or_solver_run": True})
    dump(HERE / "evidence/root269-preserved-rejection.json", {"schema": "ds02.f2.stage1.fresh096.root269-preservation.v1", "source_only": True, "status": "rejected_before_registration", "reason": "strict-dispatch source absent from digest-bound inputs", "no_receipt_consumed": True, "requests": [{"case_id": c["case_id"], "request": str(c["root269_request_path"]), "request_sha256": c["root269_request_sha256"]} for c in cases], "root270_repair": binding(DISPATCH_REPAIR)})
    dump(HERE / "evidence/metadata-contract-audit.json", {"schema": "ds02.f2.stage1.fresh096.metadata-contract-audit.v1", "source_only": True, "arrays_opened": False, "checks": {"five_root270_receipts_completed0": True, "receipt_request_digests_close": True, "receipt_report_counts_close": True, "receipt_xml_counts_sum": True, "all_root270_guard_digests_bound": True, "actual_bi4_hashes_are_producer_supplied": True, "future_qa_hashes_null": True, "future_native_hashes_null": True, "root269_preserved": True, "solver_request_disabled": True}, "measured_counts_are_case_specific": True, "mass_rescale": False, "mother_counts_reused": False})
    dump(HERE / "F2_STAGE1_FRESH096_ACTUAL_GENCASERUN_QA_NATIVE_MANIFEST.json", {"schema": SCHEMA, "family_id": "F2", "scope_id": SCOPE, "handoff": HERE.name, "source_only": True, "execution_allowed": False, "launch_allowed": False, "disabled_requests": True, "actual_gencase_status": "five Root270 completed/0; producer metadata bound", "actual_gencase_does_not_grant_typed_or_visual_status": True, "root269_preservation": "all five rejected-before-registration requests remain historical and are not consumed as completed evidence", "dynamic_count_policy": "all counts copied from each Root270 receipt and prepared-input-report; no mother-count substitution", "mass_policy": "no native mass rescale; future QA reports actual XML/CSV mass only", "future_evidence_null": {"initial_qa_report_sha256": None, "frame0_csv_sha256": None, "native_solver_receipt_sha256": None, "native_output_hash": None, "visual_acceptance": None}, "root230_native_recipe": {"command": ["DualSPHysics5.4_linux64", "{gencase_prefix}", "{attempt_root}/solver_output", "-tmax:4.0", "-tout:0.01"], "time_max_s": 4.0, "time_out_s": 0.01, "frames": 401, "no_mdbc_or_noslip": True}, "cases": rows, "claims": {"gen_case": True, "initial_qa": False, "native_solver": False, "typed": False, "visual": False, "qualification": False, "production": False}})
    readme = f"""# F2 fresh096 actual GenCase bound QA/native handoff\n\nThis source-only package binds the five Root270 GenCase attempts for the fresh095 RX047/RX050/RX055/RX060/RX063 conditions. Each receipt is completed with return code 0 and its own generated XML, BI4 producer hash, prepared-input report, and measured particle counts. The measured counts are kept per case; no mother count or mass is substituted.\n\nThe five disabled `actual-initial-qa` requests use the reviewed dynamic PartVTK worker and point to the actual Root270 receipt. Root may enable a request through the shared CPU runner to produce a bounded frame-zero report. The five disabled Root230 native requests carry the actual GenCase receipt/report/XML/BI4 producer bindings, but keep QA and native output hashes null and remain forbidden until the corresponding actual QA passes. The exact native command is the existing full 4.0 s / 0.01 s / 401-frame command with no added mDBC/no-slip option.\n\nRoot269's strict-dispatch preflight rejection is preserved as historical evidence and is never treated as a completed GenCase. Root270 runtime, strict-dispatch, Root142 home-floor, resource-window, Root230 home-floor, source-policy, and GPU-policy digests are recorded. No GenCase, PartVTK, solver, array reader, shared registry, or ledger was run or modified by this package.\n\n`build_fresh096.py` is a metadata-only regeneration helper. The copied `f2_stage1_initial_qa_worker_v2.py` is disabled source for Root's later CPU audit; it is not executed here.\n"""
    (HERE / "README.md").write_text(readme, encoding="utf-8")
    shutil.copyfile(Path(__file__).resolve(), HERE / "build_fresh096.py")


if __name__ == "__main__":
    build()
    print(json.dumps({"package": str(HERE), "cases": list(CASE_IDS), "requests_disabled": True}, indent=2))
