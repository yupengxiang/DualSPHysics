#!/usr/bin/env python3
"""Build the F3 four-corner Root706 -> NVMe typed source handoff.

This is metadata-only.  It consumes JSON/source metadata and producer supplied
payload digests.  It never opens or hashes BI4/CSV/H5/VTK/DAT/numerical arrays,
and never launches a converter.  The historical fresh066 five-case package is
left untouched; this sibling is the collision-safe fresh066 corner assignment.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Mapping

F3 = Path("/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics")
INT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
LAB = INT / "lagrangian-fluid-lab"
BASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3")
HERE = Path(__file__).resolve().parent
SRC065 = F3 / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_065_stage1_first48_pitch_ay_source_v1"
R704 = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f3_new24_exact_initial_forcing_preparation_launch_owner_repair1_704"
R706 = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f3_new24_pitch_AY_four_corner_full836_native_qualification_706"
R707 = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f3_four_corner_native706_idle_UUID_shared4_controller_707"
R719 = LAB / "campaigns/ds-data-02/handoff_20261003/root_latest_user_resource_window_confirmation_and_F3_four_native_terminal_719"
CONVERTER = LAB / "scripts/ds_data02_direct_convert.py"
PYTHON = LAB / ".venv/bin/python"
WRAPPER = LAB / "scripts/ds_data02_nvme_convert_v1.py"
AUDIT = LAB / "scripts/ds_data02_f3_nvme_input_audit_v1.py"
DS_CONVERT = LAB / "scripts/ds_data02_convert.py"
STRICT = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
R142_LAUNCH = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/launch.py"
R142_POLICY = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/policy-check.json"
R142_SOURCE = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/source-policy-contract.json"
RESOURCE = LAB / "campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
DECODER = BASE / "campaigns/l1-resume/artifacts/bi4_dump"
PARTVTK = BASE / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
DECODER_SHA = "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
PARTVTK_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
CASES = ("F3_STAGE1_DP006_P0800_AY0250", "F3_STAGE1_DP006_P0800_AY0750", "F3_STAGE1_DP006_P1200_AY0250", "F3_STAGE1_DP006_P1200_AY0750")
ASSIGNMENT = "fresh066-corner706"
SCOPE = "F3_STAGE1_FIRST48_PITCH_AY_CORNER_QUALIFICATION_V1"
PAYLOAD_SUFFIXES = {".bi4", ".obi4", ".csv", ".dat", ".h5", ".hdf5", ".vtk", ".npy", ".npz"}


def load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def dump(p: Path, value: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require(p: Path, directory: bool = False) -> Path:
    p = Path(p).resolve()
    if directory and not p.is_dir():
        raise FileNotFoundError(p)
    if not directory and not p.is_file():
        raise FileNotFoundError(p)
    return p


def metadata_sha(p: Path) -> str:
    p = require(p)
    if p.suffix.lower() in PAYLOAD_SUFFIXES:
        raise AssertionError(f"payload hashing forbidden: {p}")
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def add_input(inputs: OrderedDict[str, str], p: Path | str, sha: str | None = None, payload: bool = False) -> None:
    lexical = Path(p)
    p = require(lexical)
    if sha is None:
        if payload or p.suffix.lower() in PAYLOAD_SUFFIXES:
            raise AssertionError(f"no producer digest for payload: {p}")
        sha = metadata_sha(p)
    # Preserve the approved virtualenv path in the request.  ``Path.resolve``
    # would collapse its symlink to /usr/bin/python3.10, which is a different
    # runtime input even though it has the same bytes.
    display = str(lexical) if lexical.resolve() == PYTHON.resolve() else str(p)
    old = inputs.get(display)
    if old is not None and old != sha:
        raise AssertionError(f"input digest conflict for {display}: {old} != {sha}")
    inputs[display] = str(sha)


def probe_converter() -> Any:
    if Path(sys.executable).resolve() != PYTHON.resolve():
        raise RuntimeError(f"use approved virtualenv: {PYTHON}")
    spec = importlib.util.spec_from_file_location("_fresh066_corner_direct_convert", CONVERTER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import converter metadata module")
    module = importlib.util.module_from_spec(spec)
    old = sys.modules.get(spec.name)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if old is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = old
    return module


def corner_rows() -> tuple[dict[str, Any], str, dict[str, Any]]:
    review_path = require(R719 / "latest-resource-confirmation-and-native-terminal-review.json")
    review_sha = metadata_sha(review_path)
    review = load(review_path)
    rows = {x["case_id"]: x for x in review["F3_four_actual_native_completed0"]}
    if set(rows) != set(CASES):
        raise AssertionError(f"Root719 case set drift: {sorted(rows)}")
    controller = load(require(R707 / "controller-result.json"))
    crows = {x["case_id"]: x for x in controller["results"]}
    if set(crows) != set(CASES) or controller.get("completed0") != 4:
        raise AssertionError("Root707 did not attest exactly four completed/0 cases")
    for case in CASES:
        actual = rows[case]["actual_native"]
        if actual.get("status") != "completed" or actual.get("returncode") != 0:
            raise AssertionError(f"{case}: Root719 not completed/0")
        if rows[case].get("native_saved_frame_filename_count") != 836:
            raise AssertionError(f"{case}: Root719 frame count drift")
        if crows[case].get("status") != "completed" or crows[case].get("returncode") != 0:
            raise AssertionError(f"{case}: Root707 not completed/0")
    return rows, review_sha, controller


def input_path(nreq: Mapping[str, Any], suffix: str) -> Path:
    hits = [Path(x) for x in nreq.get("input_files", []) if Path(x).suffix.lower() == suffix]
    if len(hits) != 1:
        raise AssertionError(f"{nreq.get('case_id')}: expected one {suffix}, found {hits}")
    return hits[0].resolve()


def producer_digest(nreq: Mapping[str, Any], p: Path) -> str:
    sha = nreq.get("input_sha256", {}).get(str(p))
    if not sha:
        raise AssertionError(f"producer omitted digest for {p}")
    return str(sha)


def source_tuple(nreq: Mapping[str, Any]) -> dict[str, Any]:
    b = nreq["physical_binding"]
    p = b["parameters"]
    return {"mechanism_id": b["mechanism_id"], "nominal_pitch_multiplier": p["nominal_pitch_multiplier"], "transverse_amplitude_m_s2": p["transverse_amplitude_m_s2"]}


def native_record(nreq: Mapping[str, Any], row: Mapping[str, Any], req_ref: dict[str, str], rec_ref: dict[str, str]) -> dict[str, Any]:
    xml, bi4, csv = input_path(nreq, ".xml"), input_path(nreq, ".bi4"), input_path(nreq, ".csv")
    root = Path(nreq["attempt_root"]).resolve()
    return {
        "case_id": nreq["case_id"], "physical_case_id": nreq["physical_case_id"], "attempt_id": nreq["attempt_id"],
        "attempt_root": str(root), "data_root": str(root / "solver_output/data"),
        "native_receipt": rec_ref, "native_request": req_ref, "status": "completed", "returncode": 0,
        "solver_command": copy.deepcopy(nreq["command"]), "solver_cwd": nreq["cwd"],
        "expected_saved_frames": 836, "saved_frames": 836, "time_window_s": [0.0, 8.35], "save_interval_s": 0.01,
        "quality": {"actual_3d": True, "dimension": 3, "total_particles": 179208, "fixed_particles": 111708, "fluid_particles": 67500, "moving_particles": 0, "saved_frames": 836, "native_fluid_mass_kg": 14.580000000000002, "continuum_reference_mass_kg": 14.58, "mass_policy": "native_massfluid_no_rescaling"},
        "prepared_input": {
            "forcing": {"path": str(csv), "sha256": producer_digest(nreq, csv)},
            "generated_xml": {"path": str(xml), "sha256": producer_digest(nreq, xml)},
            "initial_bi4": {"path": str(bi4), "sha256": producer_digest(nreq, bi4)},
            "report": copy.deepcopy(nreq["actual_preparation_report"]),
            "preparation_receipt": copy.deepcopy(nreq["actual_preparation_receipt"]),
        },
        "gencase_receipt": {"path": nreq["gencase_receipt"], "sha256": nreq["gencase_receipt_sha256"]},
        "parent_initial_qa": copy.deepcopy(nreq["genuine_parent_initial_QA"]),
        "initial_QA_exact_clone_evidence": copy.deepcopy(nreq["initial_QA_exact_clone_evidence"]),
        "source_condition": copy.deepcopy(nreq["source_condition"]), "source_owner": copy.deepcopy(nreq["source_owner"]), "source_request": copy.deepcopy(nreq["source_request"]),
        "producer_payload_digest_provenance": {
            "source": "Root704/Root706/Root719 metadata attestations", "payloads_opened_by_source_builder": False, "payloads_rehashed_by_source_builder": False,
            "xml_sha256": producer_digest(nreq, xml), "initial_bi4_sha256": producer_digest(nreq, bi4), "forcing_sha256": producer_digest(nreq, csv),
            "solver_log_sha256": row["original_solver_log"]["sha256"],
        },
        "root719_terminal_scalar_evidence": {"saved_frame_filename_count": 836, "solver_log": copy.deepcopy(row["original_solver_log"]), "visual_acceptance": "WAIT typed/XMF/full animation"},
    }


def make_owner(nreq: Mapping[str, Any], row: Mapping[str, Any], converter: Any, req_ref: dict[str, str], rec_ref: dict[str, str], review_sha: str) -> dict[str, Any]:
    physical = copy.deepcopy(nreq["physical_binding"])
    scope = converter._physical_condition_scope({"physical_binding": physical})
    scope_sha = converter.canonical_hash(scope)
    if scope_sha != nreq["physical_condition_sha256"]:
        raise AssertionError(f"{nreq['case_id']}: converter hash mismatch {scope_sha} != {nreq['physical_condition_sha256']}")
    native = native_record(nreq, row, req_ref, rec_ref)
    tup = source_tuple(nreq)
    owner = {
        "schema": "ds02.stage1.f3.four-corner-native-typed-owner.v1", "fresh_id": ASSIGNMENT, "family_id": "F3", "case_id": nreq["case_id"],
        "physical_case_id": nreq["physical_case_id"], "physical_condition_sha256": nreq["physical_condition_sha256"], "physical_binding": physical,
        "actual_converter_physical_condition_scope": scope, "actual_converter_physical_condition_scope_sha256": scope_sha,
        "physical_condition_hash_scope": "official converter _physical_condition_scope(owner), explicit ds-data-02.physical-binding.v1; source template remains separate",
        "actual_converter_provenance": {"module": str(CONVERTER.resolve()), "module_sha256": metadata_sha(CONVERTER), "function": "_physical_condition_scope", "canonical_hash_function": "canonical_hash", "import_method": "temporary sys.modules entry restored after metadata probe", "scope_schema": scope["schema"], "source_owner_had_explicit_physical_binding": True, "scope_hash_matches_producer": True},
        "parameter_tuple": tup, "source_parameter_tuple": tup, "source_physical_condition_sha256": None, "source_canonical_physical_binding": None,
        "source_condition_template": copy.deepcopy(nreq["source_condition"]), "source_owner_template": copy.deepcopy(nreq["source_owner"]), "source_and_actual_scopes_are_distinct": True,
        "source_plan_binding": {"source_condition_template": copy.deepcopy(nreq["source_condition"]), "source_owner_template": copy.deepcopy(nreq["source_owner"]), "source_plan_condition_sha256": None, "actual_converter_scope_schema": scope["schema"], "actual_converter_scope_sha256": scope_sha, "condition_hash_is_not_recipe_hash": True, "recipe_name": "F3_DP006_ADAPTIVE_CFL05_COEF005_TMAX8P35_TOUT0P01_MDBC_NOSLIP1", "recipe_sha256": None},
        "native_full836_binding": native, "actual_native_binding": native, "actual_gencase_receipt": native["gencase_receipt"], "actual_preparation_receipt": native["prepared_input"]["preparation_receipt"], "actual_preparation_report": native["prepared_input"]["report"], "initial_QA_exact_clone_evidence": native["initial_QA_exact_clone_evidence"], "parent_initial_qa": native["parent_initial_qa"],
        "native_terminal_evidence": {"root719_review": {"path": str((R719 / "latest-resource-confirmation-and-native-terminal-review.json").resolve()), "sha256": review_sha}, "status": "completed", "returncode": 0, "saved_frame_filename_count": 836, "saved_scientific_payload_read_or_hashed_by_parent": False, "visual_acceptance": "WAIT typed/XMF/full animation"},
        "native_solver_command": copy.deepcopy(nreq["command"]), "actual_solver_command": copy.deepcopy(nreq["command"]), "actual_solver_cwd": nreq["cwd"],
        "scope_id": SCOPE, "target_scope_id": SCOPE, "nominal_pitch_multiplier": nreq["nominal_pitch_multiplier"], "transverse_amplitude_m_s2": nreq["transverse_amplitude_m_s2"], "numerical_recipe": "F3_DP006_ADAPTIVE_CFL05_COEF005_TMAX8P35_TOUT0P01_MDBC_NOSLIP1", "save_interval_s": 0.01, "event_window_s": [0.0, 8.35], "complete_event_window_s": [0.0, 8.35],
        "conversion_input_contract": {"decoder": {"path": str(DECODER.resolve()), "sha256": DECODER_SHA}, "partvtk": {"path": str(PARTVTK.resolve()), "sha256": PARTVTK_SHA}, "decoder_hash_source": "registered executable digest; source did not execute or rehash payload", "partvtk_hash_source": "registered executable digest; source did not execute PartVTK"},
        "native_input_attestation": native["producer_payload_digest_provenance"], "payload_hash_provenance": "XML/BI4/CSV/native log hashes are producer/native attestations; source did not read or rehash payloads",
        "status": "source_only_disabled_actual_native_bound_pending_typed_conversion", "source_only": True, "execution_allowed": False, "launch_allowed": False, "array_reading_by_source_builder": False, "source_agent_did_not_read_arrays": True, "source_agent_did_not_read_science_payloads": True,
        "future_typed_outputs": {"typed_execution_receipt": {"path": "{attempt_root}/execution-receipt.json", "sha256": None}, "conversion_report": {"path": "{attempt_root}/conversion-report.json", "sha256": None}, "trajectory_h5": {"path": "{attempt_root}/trajectory.h5", "sha256": None}, "partvtk_validation": {"path": "{attempt_root}/partvtk-validation", "sha256": None}, "visual_decision": None},
        "typed_scope_provenance": {"scope_id": SCOPE, "physical_condition_sha256_used_by_conversion": scope_sha, "source_physical_condition_sha256": None, "typed_receipt_sha256": None, "conversion_report_sha256": None, "trajectory_h5_sha256": None, "xmf_sha256": None, "render_hashes": None},
        "independent_case_count_increment": 0, "production_approval": "none", "q_n": "not_granted", "numerical_precision_status": "not_accepted", "visual_review_pending": True,
    }
    return owner


def static_paths() -> list[Path]:
    return [PYTHON, WRAPPER, CONVERTER, AUDIT, DS_CONVERT, STRICT, RUNTIME, R142_LAUNCH, R142_POLICY, R142_SOURCE, RESOURCE, DECODER, PARTVTK]


def build_input_closure(nreq: Mapping[str, Any], row: Mapping[str, Any], owner_path: Path, owner_sha: str, req_ref: dict[str, str], rec_ref: dict[str, str], review_sha: str) -> tuple[list[str], dict[str, str]]:
    inputs: OrderedDict[str, str] = OrderedDict()
    add_input(inputs, owner_path, owner_sha)
    for p in static_paths():
        add_input(inputs, p, DECODER_SHA if p.resolve() == DECODER.resolve() else PARTVTK_SHA if p.resolve() == PARTVTK.resolve() else None)
    add_input(inputs, Path(req_ref["path"]), req_ref["sha256"]); add_input(inputs, Path(rec_ref["path"]), rec_ref["sha256"])
    add_input(inputs, R719 / "latest-resource-confirmation-and-native-terminal-review.json", review_sha)
    add_input(inputs, R707 / "controller-result.json")
    add_input(inputs, R704 / "actual-new24-input-preparation-request.json")
    for key in ("actual_preparation_receipt", "actual_preparation_report", "genuine_parent_initial_QA", "source_condition", "source_owner", "source_request", "initial_QA_exact_clone_evidence"):
        value = nreq[key] if key in nreq else nreq["genuine_parent_initial_QA"]
        add_input(inputs, value["path"], value["sha256"])
    add_input(inputs, nreq["gencase_receipt"], nreq["gencase_receipt_sha256"])
    for suffix in (".xml", ".bi4", ".csv"):
        p = input_path(nreq, suffix); add_input(inputs, p, producer_digest(nreq, p), payload=True)
    add_input(inputs, Path(row["original_solver_log"]["path"]), row["original_solver_log"]["sha256"])
    # Keep producer-staged index metadata when present; no need to inspect its contents.
    for raw in nreq.get("input_files", []):
        p = Path(raw)
        if p.name in {"fresh065-prepared-index.json", "prepared-cases.json"}:
            sha = nreq.get("input_sha256", {}).get(str(p))
            if sha: add_input(inputs, p, sha)
    ordered = sorted(inputs)
    return ordered, {p: inputs[p] for p in ordered}


def make_request(nreq: Mapping[str, Any], row: Mapping[str, Any], owner_path: Path, owner_sha: str, owner: Mapping[str, Any], req_ref: dict[str, str], rec_ref: dict[str, str], review_sha: str) -> dict[str, Any]:
    xml = input_path(nreq, ".xml"); root = Path(nreq["attempt_root"]).resolve(); data_root = root / "solver_output/data"
    attempt = f"root-stage1-f3-{nreq['case_id'].lower()}-full836-typed-nvme-{ASSIGNMENT}"
    inputs, hashes = build_input_closure(nreq, row, owner_path, owner_sha, req_ref, rec_ref, review_sha)
    command = [str(PYTHON), str(WRAPPER.resolve()), "--staging-root", "/tmp/ds02-nvme-conversion", "--staging-limit-bytes", "25769803776", "--", "--data-root", str(data_root), "--generated-xml", str(xml), "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json", "--solver-log", str(Path(row["original_solver_log"]["path"]).resolve()), "--solver-receipt", str(Path(rec_ref["path"]).resolve()), "--gencase-receipt", str(Path(nreq["gencase_receipt"]).resolve()), "--decoder", str(DECODER.resolve()), "--partvtk", str(PARTVTK.resolve()), "--validation-dir", "{attempt_root}/partvtk-validation", "--keep-validation-csv", "--owner-metadata", str(owner_path.resolve()), "--particle-chunk", "65536"]
    if str(CONVERTER.resolve()) in command[command.index("--") + 1:]:
        raise AssertionError("direct_converter.py must not occur after the NVMe wrapper --")
    return {
        "schema": "ds02.runner-request.v2", "fresh_id": ASSIGNMENT, "family_id": "F3", "case_id": nreq["case_id"], "attempt_id": attempt, "attempt_root": str(DATA / nreq["case_id"] / attempt), "command": command, "cwd": str(LAB.resolve()), "worktree_root": str(F3.resolve()), "kind": "cpu", "cpu_task_kind": "conversion", "cpu_threads": 2, "max_wall_seconds": 10800, "estimated_storage_bytes": 25769803776, "launch_owner": "root",
        "disabled": True, "launch": False, "launch_allowed": False, "execution_allowed": False, "source_only": True, "status": "disabled_pending_root_actual_nvme_conversion", "request_status": "source_only_disabled_actual_native_bound_pending_typed_conversion", "root_review_required": True, "root_dataset_inventory_profile": "root_home_floor_no_legacy_dataset_walk_v1", "root_scope": "Four Root706 pitch/AY corners; native is completed/0, but typed/XMF/render/visual evidence is future.",
        "root_enablement_requirements": ["wait for F6 conversion queue/tool1704 to reach terminal", "strict CPU conversion cap2 reservation", "actual typed receipt/report/PartVTK evidence", "Root visual review; no Q-N/precision claim"], "scope_id": SCOPE, "target_scope_id": SCOPE, "physical_case_id": nreq["physical_case_id"], "physical_condition_sha256": nreq["physical_condition_sha256"], "actual_converter_physical_condition_scope": copy.deepcopy(owner["actual_converter_physical_condition_scope"]), "actual_converter_physical_condition_scope_sha256": owner["actual_converter_physical_condition_scope_sha256"], "physical_condition_hash_scope": owner["physical_condition_hash_scope"], "physical_binding": copy.deepcopy(owner["physical_binding"]), "source_physical_condition_sha256": None, "source_parameter_tuple": copy.deepcopy(owner["source_parameter_tuple"]), "source_and_actual_scopes_are_distinct": True, "parameter_tuple": copy.deepcopy(owner["parameter_tuple"]), "numerical_recipe": owner["numerical_recipe"], "physical_window_s": [0.0, 8.35], "expected_saved_frames": 836, "expected_particles": 179208, "expected_fluid_particles": 67500, "expected_fixed_particles": 111708, "expected_moving_particles": 0,
        "native_full836_binding": copy.deepcopy(owner["native_full836_binding"]), "actual_native_binding": copy.deepcopy(owner["actual_native_binding"]), "native_input_unchanged": True, "native_solver_command": copy.deepcopy(nreq["command"]), "genuine_gencase_receipt": copy.deepcopy(owner["actual_gencase_receipt"]), "parent_initial_qa": copy.deepcopy(owner["parent_initial_qa"]), "owner_metadata": {"path": str(owner_path.resolve()), "sha256": owner_sha}, "actual_converter_owner": {"path": str(owner_path.resolve()), "sha256": owner_sha}, "decoder_binding": {"path": str(DECODER.resolve()), "sha256": DECODER_SHA}, "partvtk_binding": {"path": str(PARTVTK.resolve()), "sha256": PARTVTK_SHA},
        "nvme_staging": {"staging_root": "/tmp/ds02-nvme-conversion", "staging_limit_bytes": 25769803776, "free_space_floor_bytes": 107374182400, "max_parallel_conversions": 2}, "resource_guards": {"conversion_concurrency_cap": 2, "cpu_threads_per_request": 2, "home_free_space_floor_gib": 500, "nvme_free_space_floor_bytes": 107374182400, "nvme_staging_limit_bytes": 25769803776, "source_resource_window": str(RESOURCE.resolve())},
        "input_files": inputs, "input_sha256": hashes, "payload_hash_provenance": "XML/BI4/CSV/native log digests are producer/native attestations; source builder did not read or rehash payloads", "source_builder_did_not_read_science_payloads": True, "array_input_hashes_are_registered_not_source_read": True,
        "future_typed_outputs": {"typed_execution_receipt": {"path": "{attempt_root}/execution-receipt.json", "sha256": None}, "conversion_report": {"path": "{attempt_root}/conversion-report.json", "sha256": None}, "trajectory_h5": {"path": "{attempt_root}/trajectory.h5", "sha256": None}, "partvtk_validation": {"path": "{attempt_root}/partvtk-validation", "sha256": None}, "visual_decision": None}, "independent_case_count_increment": 0, "production_approval": "none", "q_n": "not_granted", "numerical_precision_status": "not_accepted", "visual_review_pending": True, "new_physics_or_gencase": False,
        "source_refs": {"root704_preparation_request": {"path": str((R704 / "actual-new24-input-preparation-request.json").resolve()), "sha256": metadata_sha(R704 / "actual-new24-input-preparation-request.json")}, "root706_native_request": req_ref, "root707_controller": {"path": str((R707 / "controller-result.json").resolve()), "sha256": metadata_sha(R707 / "controller-result.json")}, "root719_terminal_review": {"path": str((R719 / "latest-resource-confirmation-and-native-terminal-review.json").resolve()), "sha256": review_sha}},
    }


def build() -> None:
    require(SRC065, True); require(R706, True); require(R707 / "controller-result.json")
    rows, review_sha, controller = corner_rows(); converter = probe_converter()
    cases = []; selection = []
    for case in CASES:
        row = rows[case]; req_ref = {"path": str(Path(row["actual_native"]["request"]["path"]).resolve()), "sha256": row["actual_native"]["request"]["sha256"]}; rec_ref = {"path": str(Path(row["actual_native"]["receipt"]["path"]).resolve()), "sha256": row["actual_native"]["receipt"]["sha256"]}
        npath, rpath = Path(req_ref["path"]), Path(rec_ref["path"]); nreq, receipt = load(npath), load(rpath)
        if metadata_sha(npath) != req_ref["sha256"] or metadata_sha(rpath) != rec_ref["sha256"]: raise AssertionError(f"{case}: Root719 digest mismatch")
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0: raise AssertionError(f"{case}: receipt not completed/0")
        owner_path = HERE / "owners" / f"{case}.json"; owner = make_owner(nreq, row, converter, req_ref, rec_ref, review_sha); dump(owner_path, owner); owner_sha = metadata_sha(owner_path)
        request_path = HERE / "requests" / f"{case}.json"; request = make_request(nreq, row, owner_path, owner_sha, owner, req_ref, rec_ref, review_sha); dump(request_path, request); request_sha = metadata_sha(request_path)
        cases.append({"case_id": case, "physical_case_id": nreq["physical_case_id"], "physical_condition_sha256": nreq["physical_condition_sha256"], "native_request": req_ref, "native_receipt": rec_ref, "owner": {"path": str(owner_path.resolve()), "sha256": owner_sha}, "typed_request": {"path": str(request_path.resolve()), "sha256": request_sha}, "native_status": "completed/0", "saved_frames": 836, "counts": {"total": 179208, "fixed": 111708, "fluid": 67500, "moving": 0, "dimension": 3}, "visual_status": "WAIT"})
        selection.append({"case_id": case, "physical_case_id": nreq["physical_case_id"], "pitch": nreq["nominal_pitch_multiplier"], "ay": nreq["transverse_amplitude_m_s2"], "physical_condition_sha256": nreq["physical_condition_sha256"], "source_condition": nreq["source_condition"], "source_owner": nreq["source_owner"], "actual_preparation_report": nreq["actual_preparation_report"], "native_request": req_ref, "native_receipt": rec_ref})
    review_path = R719 / "latest-resource-confirmation-and-native-terminal-review.json"
    prep_path = R704 / "actual-new24-input-preparation-request.json"
    ctrl_path = R707 / "controller-result.json"
    dump(HERE / "metadata/selection.json", {"schema": "ds02.stage1.f3.four-corner-native706-selection.v1", "assignment_id": ASSIGNMENT, "scope_id": SCOPE, "cases": selection, "root704_preparation_request": {"path": str(prep_path.resolve()), "sha256": metadata_sha(prep_path)}, "root707_controller": {"path": str(ctrl_path.resolve()), "sha256": metadata_sha(ctrl_path)}, "root719_terminal_review": {"path": str(review_path.resolve()), "sha256": review_sha}})
    dump(HERE / "source-binding.json", {"schema": "ds02.stage1.f3.four-corner-typed-source-binding.v1", "assignment_id": ASSIGNMENT, "historical_fresh066_package_preserved": str((HERE.parent / "root_followup_066_stage1_first24_typed_nvme_source_v1").resolve()), "source065": {"path": str(SRC065.resolve()), "source_only": True}, "actual_evidence": {"root704": {"path": str(prep_path.resolve()), "sha256": metadata_sha(prep_path)}, "root707": {"path": str(ctrl_path.resolve()), "sha256": metadata_sha(ctrl_path)}, "root719": {"path": str(review_path.resolve()), "sha256": review_sha}}, "scope_id": SCOPE, "all_cases_actual_native_completed0": True, "all_cases_actual_native_saved_frames": 836, "counts": {"total": 179208, "fixed": 111708, "fluid": 67500, "moving": 0, "dimension": 3}, "future_typed_receipts": None, "future_h5_hashes": None, "future_visual_decisions": None, "production_approval": "none", "q_n": "not_granted", "independent_case_count_increment": 0, "source_builder_science_payload_access": "none; producer/native attestations only", "root_conversion_queue_note": "Root waits for F6 conversion queue/tool1704 terminal before cap2 conversion."})
    dump(HERE / "manifest.json", {"schema": "ds02.stage1.f3.four-corner-native706-typed-nvme-manifest.v1", "assignment_id": ASSIGNMENT, "family_id": "F3", "case_count": 4, "case_ids": list(CASES), "scope_id": SCOPE, "source_only": True, "all_requests_disabled": True, "all_native_completed0": True, "expected_saved_frames": 836, "counts": {"total": 179208, "fixed": 111708, "fluid": 67500, "moving": 0, "dimension": 3}, "recipe": {"tmax_s": 8.35, "tout_s": 0.01, "frames": 836, "solver_mode": "-mdbc_noslip:1"}, "nvme": {"staging_root": "/tmp/ds02-nvme-conversion", "staging_limit_bytes": 25769803776, "free_space_floor_bytes": 107374182400, "max_parallel_conversions": 2}, "future_typed_receipt_sha256": None, "future_conversion_report_sha256": None, "future_trajectory_h5_sha256": None, "future_visual_decisions": None, "numerical_precision_status": "not_accepted", "production_approval": "none", "q_n": "not_granted", "independent_case_count_increment": 0, "cases": cases})


if __name__ == "__main__":
    build(); print(f"built {ASSIGNMENT} at {HERE}")
