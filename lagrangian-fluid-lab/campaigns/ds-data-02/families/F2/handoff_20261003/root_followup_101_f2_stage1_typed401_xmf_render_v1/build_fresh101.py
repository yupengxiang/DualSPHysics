#!/usr/bin/env python3
"""Build the F2 fresh101 legacy-aware XMF and Root023 render handoff.

This builder consumes only JSON/XML/Python metadata from fresh100 and the
source definition.  It deliberately does not open or hash motion ``.dat``
files, typed HDF5, native BI4, CSV, or any other scientific payload.  Those
paths are carried as future producer inputs with null digests for the Root
owned execution chain.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


INFRA = Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
BASE = Path("/home/jade/Projects/DualSPHysics").resolve()
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
HERE = Path(__file__).resolve().parent
FRESH100 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_100_f2_stage1_motion_entry_metadata_adapter_v1"
MANIFEST100 = FRESH100 / "F2_STAGE1_FRESH100_MOTION_ENTRY_MANIFEST.json"
LAB = INTEGRATION / "lagrangian-fluid-lab"
PYTHON = LAB / ".venv/bin/python"
DIRECT = LAB / "scripts/ds_data02_direct_convert.py"
NVME = LAB / "scripts/ds_data02_nvme_convert_v1.py"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
STRICT = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
ROOT142 = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py"
ROOT230D = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT230 = ROOT230D / "root_native_home_floor_inventory_policy.py"
ROOT230LAUNCH = ROOT230D / "launch.py"
ROOT230CONTRACT = ROOT230D / "source-policy-contract.json"
GPU_POLICY = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
RESOURCE = LAB / "campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
SCOPE = "F2_STAGE1_FIRST24_DOMAIN_EXPANSION_V1"
ROOT142_PROFILE = "root_home_floor_no_legacy_dataset_walk_v1"
ROOT230_PROFILE = "root_home_floor_no_legacy_dataset_walk_native_v1"
RESOURCE_CONTRACT = {
    "conversion_concurrency": 2,
    "cpu_threads": 2,
    "home_min_free_bytes": 536870912000,
    "nvme_free_space_floor_bytes": 107374182400,
    "nvme_staging_peak_limit_bytes": 25769803776,
    "nvme_staging_root": "/tmp/ds02-nvme-conversion",
    "max_wall_seconds": 5400,
}
STRICT_GUARD_DIGEST = "a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a"
RAW_SUFFIXES = {".dat", ".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}
STATIC_SUFFIXES = {".json", ".xml", ".py", ".md", ".txt"}


def sha(path: Path) -> str:
    """Hash only package metadata and source text; refuse scientific files."""
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f"scientific payload hash refused: {path}")
    if path.suffix.lower() not in STATIC_SUFFIXES:
        raise ValueError(f"non-metadata input refused: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size, "exists": True}


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def unique(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"metadata root must be an object: {path}")
    return value


def static_files(*paths: Path) -> list[Path]:
    result = unique(list(paths))
    for path in result:
        if path.suffix.lower() in RAW_SUFFIXES:
            raise AssertionError(f"fresh101 static closure contains scientific payload: {path}")
        sha(path)
    return result


def future_map(paths: list[Path]) -> tuple[list[str], dict[str, None]]:
    values = [str(Path(path).resolve()) for path in unique(paths)]
    return values, {value: None for value in values}


def strict_guard(template: dict[str, Any], *, native: bool) -> dict[str, Any]:
    guard = dict(template.get("strict_guard") or {
        "estimated_storage_bytes": 34359738368,
        "input_closure": "set(input_files)==set(input_sha256); metadata-only; future producer payloads remain null",
        "resource_window": {"path": str(RESOURCE.resolve()), "sha256": sha(RESOURCE)},
        "root142_inventory_policy": {"path": str(ROOT142.resolve()), "sha256": sha(ROOT142)},
        "runtime_v2": {"path": str(RUNTIME.resolve()), "sha256": sha(RUNTIME)},
        "strict_dispatch": {"path": str(STRICT.resolve()), "sha256": sha(STRICT)},
        "worktree_root": str(INFRA),
    })
    guard["source_only"] = True
    guard["worktree_root"] = str(INFRA)
    guard["input_closure"] = "set(input_files)==set(input_sha256); metadata-only; future producer payloads remain null"
    guard["strict_guard_digest"] = template["strict_guard_digest"]
    return guard


def common_request(meta: dict[str, Any], owner_path: Path, files: list[Path], attempt: str,
                   template: dict[str, Any], *, native: bool) -> dict[str, Any]:
    owner = read_json(owner_path)
    files = static_files(*files)
    return {
        "schema": "ds02.runner-request.v3",
        "family_id": "F2",
        "scope_id": SCOPE,
        "case_id": meta["case_id"],
        "physical_case_id": meta["physical_case_id"],
        "physical_condition_sha256": owner["typed_scope_contract"]["prospective_legacy_scope_sha256"],
        "source_plan_physical_condition_sha256": meta["source_plan_physical_condition_sha256"],
        "canonical_physical_binding_sha256": None,
        "prospective_legacy_scope_sha256": owner["typed_scope_contract"]["prospective_legacy_scope_sha256"],
        "producer_scope_schema": "legacy-owner-scope.v0",
        "source_only": True,
        "execution_allowed": False,
        "launch_allowed": False,
        "launch": False,
        "launch_owner": "root",
        "root_only": True,
        "root_review_required": True,
        "disabled": True,
        "future_hashes_null": True,
        "no_arrays_read": True,
        "no_science_payload_bound": True,
        "no_jobs_started": True,
        "no_shared_registry_write": True,
        "production_claim": "none",
        "qualification_claim": "none",
        "numerical_precision_status": "not accepted",
        "attempt_id": attempt,
        "worktree_root": str(INFRA),
        "raw_output_root": str((DATA_ROOT / "families" / "F2" / meta["case_id"]).resolve()),
        "input_files": [str(path) for path in files],
        "input_sha256": {str(path): sha(path) for path in files},
        "strict_guard_digest": template["strict_guard_digest"],
        "strict_guard": strict_guard(template, native=native),
        "root_dataset_inventory_profile": ROOT230_PROFILE if native else ROOT142_PROFILE,
        "root_inventory_policy_source": str((ROOT230 if native else ROOT142).resolve()),
        "root_inventory_policy_source_sha256": sha(ROOT230 if native else ROOT142),
        "resource_contract": RESOURCE_CONTRACT,
        "resource_window": str(RESOURCE.resolve()),
        "resource_window_sha256": sha(RESOURCE),
    }


def make_case(row: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    cid = row["case_id"]
    meta_path = Path(row["metadata"]["path"]).resolve()
    owner_path = Path(row["owner"]["path"]).resolve()
    meta = read_json(meta_path)
    owner = read_json(owner_path)
    typed_request_path = Path(row["requests"]["typed"]["path"]).resolve()
    native_request_path = Path(row["requests"]["native"]["path"]).resolve()
    gencase_request_path = Path(row["requests"]["gencase"]["path"]).resolve()
    qa_request_path = Path(row["requests"]["initial-qa"]["path"]).resolve()
    typed = read_json(typed_request_path)
    native = read_json(native_request_path)
    gencase = read_json(gencase_request_path)
    qa = read_json(qa_request_path)
    raw_root = Path(typed["raw_output_root"]).resolve()
    typed_attempt = typed["attempt_id"]
    native_attempt = native["attempt_id"]
    gencase_attempt = gencase["attempt_id"]
    qa_attempt = qa["attempt_id"]
    typed_root = raw_root / typed_attempt
    native_root = raw_root / native_attempt
    gencase_root = raw_root / gencase_attempt
    qa_root = raw_root / qa_attempt
    typed_receipt = typed_root / "execution-receipt.json"
    conversion_report = typed_root / "conversion-report.json"
    trajectory_h5 = typed_root / "trajectory.h5"
    native_receipt = native_root / "execution-receipt.json"
    native_log = native_root / "solver_output" / "Run.out"
    native_data = native_root / "solver_output" / "data"
    gencase_receipt = gencase_root / "execution-receipt.json"
    prepared_xml = gencase_root / "prepared" / f"{cid}.xml"
    prepared_report = gencase_root / "prepared" / "prepared-input-report.json"
    qa_report = qa_root / "actual-initial-qa.json"
    slug = cid.lower()
    xmf_attempt = f"root-stage1-f2-{slug}-full401-xmf-101"
    render_attempt = f"root-stage1-f2-{slug}-full401-root023-render-101"
    xmf_root = raw_root / xmf_attempt
    render_root = raw_root / render_attempt
    xmf_case = xmf_root / "xdmf" / "case.xmf"
    xmf_manifest = xmf_root / "xdmf" / "manifest.json"

    xmf_binding_path = HERE / "xmf/bindings" / f"{cid}.xmf-binding.json"
    render_binding_path = HERE / "render/bindings" / f"{cid}.render-binding.json"
    xmf_worker = HERE / "workers/export_xmf.py"
    render_worker = HERE / "workers/render_native023.py"

    source_definition = Path(owner["source"]["definition"]["path"]).resolve()
    source_metadata = Path(owner["source"]["metadata"]["path"]).resolve()
    motion_binding = Path(owner["source"]["motion_gencase_binding"]["path"]).resolve()
    contracts = [HERE / "metadata/contracts/xmf-contract.json",
                 HERE / "metadata/contracts/render-contract.json",
                 HERE / "metadata/contracts/typed-conversion-contract.json",
                 HERE / "metadata/contracts/runtime-strict-guard.json",
                 HERE / "metadata/base-binary-contract.json"]
    source100_manifest = MANIFEST100
    metadata_only_contract = HERE / "metadata/legacy-scope-preflight.json"
    common_static = [
        owner_path, meta_path, source_definition, source_metadata, motion_binding,
        typed_request_path, native_request_path, gencase_request_path, qa_request_path,
        source100_manifest, metadata_only_contract, *contracts, xmf_worker, render_worker,
        RUNTIME, STRICT, ROOT142, ROOT230, ROOT230LAUNCH, ROOT230CONTRACT,
        GPU_POLICY, RESOURCE,
    ]

    legacy_scope = owner["typed_scope_contract"]["prospective_legacy_scope_sha256"]
    source_plan = meta["source_plan_physical_condition_sha256"]
    metadata_hashes = {str(path): sha(path) for path in static_files(*common_static)}
    expected_contract = {
        "dimension": 3,
        "frames": 401,
        "particle_counts": None,
        "type_partition": None,
        "key": "(Zone,Idp)",
        "counts_source": "actual conversion-report and prepared-input-report only",
    }
    xmf_binding = {
        "schema": "ds02.f2.stage1.fresh101.xmf-binding.v1",
        "fresh_id": "fresh101", "family_id": "F2", "scope_id": SCOPE,
        "case_id": cid, "physical_case_id": meta["physical_case_id"],
        "producer_scope_schema": "legacy-owner-scope.v0",
        "semantic_binding_status": "legacy-owner scope only; canonical physical binding not granted",
        "physical_condition_sha256": legacy_scope,
        "source_plan_physical_condition_sha256": source_plan,
        "canonical_physical_binding_sha256": None,
        "canonical_grant": False,
        "owner_metadata": str(owner_path), "owner_metadata_sha256": sha(owner_path),
        "typed_binding": str(typed_request_path), "typed_binding_sha256": sha(typed_request_path),
        "typed_receipt": str(typed_receipt), "typed_receipt_sha256": None,
        "conversion_report": str(conversion_report), "conversion_report_sha256": None,
        "trajectory_h5": str(trajectory_h5), "trajectory_h5_sha256": None,
        "native_receipt": str(native_receipt), "native_receipt_sha256": None,
        "gencase_receipt": str(gencase_receipt), "gencase_receipt_sha256": None,
        "prepared_input_report": str(prepared_report), "prepared_input_report_sha256": None,
        "initial_qa_report": str(qa_report), "initial_qa_report_sha256": None,
        "source_definition": str(source_definition), "source_definition_sha256": sha(source_definition),
        "source_metadata": str(source_metadata), "source_metadata_sha256": sha(source_metadata),
        "expected_dimension": 3, "expected_native_frames": 401, "expected_particles": None,
        "physical_window_s": [0.0, 4.0], "save_interval_s": 0.01,
        "all_native_frames_required": True,
        "expected_native_contract": expected_contract,
        "xmf_shape_contract": {
            "dynamic_vector_dimensions": "{actual_particles} 3",
            "dynamic_scalar_dimensions": "{actual_particles}",
            "particle_axis_preserved": True,
            "counts_from_actual_conversion_report": True,
        },
        "bound_metadata_sha256": metadata_hashes,
        "future_hashes_null": True, "source_only": True,
        "disabled": True, "execution_allowed": False, "launch_allowed": False,
        "independent_case_increment": 0,
        "visual_status": "pending actual Root023 full401 render review",
        "numerical_precision_status": "not accepted",
        "output_dir_contract": "{attempt_root}/xdmf must start empty; receipt/stdout remain in attempt root",
        "future_outputs": {
            "case_xmf": None, "case_xmf_sha256": None,
            "manifest": None, "manifest_sha256": None,
            "execution_receipt": None, "execution_receipt_sha256": None,
        },
    }
    dump(xmf_binding_path, xmf_binding)

    render_binding = {
        "schema": "ds02.f2.stage1.fresh101.render-binding.v1",
        "fresh_id": "fresh101", "family_id": "F2", "scope_id": SCOPE,
        "case_id": cid, "physical_case_id": meta["physical_case_id"],
        "producer_scope_schema": "legacy-owner-scope.v0",
        "semantic_binding_status": "legacy-owner scope only; canonical physical binding not granted",
        "physical_condition_sha256": legacy_scope,
        "source_plan_physical_condition_sha256": source_plan,
        "canonical_physical_binding_sha256": None,
        "canonical_grant": False,
        "owner_metadata": str(owner_path), "owner_metadata_sha256": sha(owner_path),
        "typed_binding": str(typed_request_path), "typed_binding_sha256": sha(typed_request_path),
        "typed_receipt": str(typed_receipt), "typed_receipt_sha256": None,
        "conversion_report": str(conversion_report), "conversion_report_sha256": None,
        "trajectory_h5": str(trajectory_h5), "trajectory_h5_sha256": None,
        "native_receipt": str(native_receipt), "native_receipt_sha256": None,
        "xmf_binding": str(xmf_binding_path), "xmf_binding_sha256": sha(xmf_binding_path),
        "xmf_case": str(xmf_case), "xmf_case_sha256": None,
        "xmf_manifest": str(xmf_manifest), "xmf_manifest_sha256": None,
        "expected_dimension": 3, "expected_native_frames": 401, "expected_particles": None,
        "physical_window_s": [0.0, 4.0], "save_interval_s": 0.01,
        "expected_native_contract": expected_contract,
        "camera_policy": {
            "bounds_source": "Root023 scans every native valid position across every saved frame",
            "camera_bounds_in_manifest": False, "domain_bounds_in_manifest": False,
            "fixed_camera_override": False, "native_geometry_retained": True,
        },
        "contact_pages": 17,
        "bound_metadata_sha256": {str(path): sha(path) for path in static_files(*common_static, xmf_binding_path)},
        "future_hashes_null": True, "source_only": True,
        "disabled": True, "execution_allowed": False, "launch_allowed": False,
        "independent_case_increment": 0,
        "visual_status": "pending actual Root023 full401 render review",
        "numerical_precision_status": "not accepted",
        "output_dir_contract": "{attempt_root}/render must start empty; receipt/stdout remain in attempt root",
        "future_outputs": {
            "execution_receipt": None, "execution_receipt_sha256": None,
            "report": None, "report_sha256": None,
            "frames_dir": None, "frames_sha256": None,
            "contact_sheets": None, "gif": None, "gif_sha256": None,
            "pvsm": None, "pvsm_sha256": None,
        },
    }
    dump(render_binding_path, render_binding)

    xmf_static = static_files(*common_static, xmf_binding_path)
    render_static = static_files(*common_static, xmf_binding_path, render_binding_path)
    future_xmf_paths = [typed_receipt, conversion_report, trajectory_h5, native_receipt,
                        gencase_receipt, prepared_xml, prepared_report, qa_report,
                        native_log, native_data]
    future_render_paths = [typed_receipt, conversion_report, trajectory_h5, native_receipt,
                           xmf_case, xmf_manifest]
    future_xmf_files, future_xmf_sha = future_map(future_xmf_paths)
    future_render_files, future_render_sha = future_map(future_render_paths)

    xreq = common_request(meta, owner_path, xmf_static, xmf_attempt, template, native=False)
    xreq.update({
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2,
        "max_wall_seconds": 5400, "estimated_storage_bytes": 34359738368,
        "command": [str(PYTHON), str(xmf_worker), "--binding", str(xmf_binding_path),
                    "--output-dir", "{attempt_root}/xdmf"],
        "cwd": str(HERE),
        "depends_on_attempts": [gencase_attempt, qa_attempt, native_attempt, typed_attempt],
        "typed_receipt": str(typed_receipt), "typed_receipt_sha256": None,
        "native_receipt": str(native_receipt), "native_receipt_sha256": None,
        "conversion_report": str(conversion_report), "conversion_report_sha256": None,
        "trajectory_h5": str(trajectory_h5), "trajectory_h5_sha256": None,
        "expected_dimension": 3, "expected_native_frames": 401, "expected_particles": None,
        "expected_native_contract": expected_contract,
        "physical_condition_hash_scope": {
            "source_plan_physical_condition_sha256": source_plan,
            "prospective_legacy_scope_sha256": legacy_scope,
            "actual_converter_physical_condition_sha256": None,
            "canonical_physical_binding_sha256": None, "canonical_grant": False,
        },
        "future_input_files": future_xmf_files,
        "future_input_sha256": future_xmf_sha,
        "future_outputs": xmf_binding["future_outputs"],
        "output_contract": {"case_xmf_sha256": None, "manifest_sha256": None,
                            "actual_frame_count": None, "actual_particle_counts": None,
                            "trajectory_h5_sha256": None},
        "disabled_reason": "Enable only after actual completed/0 typed conversion, native receipt, GenCase and QA metadata are independently reviewed.",
    })
    xreq_path = HERE / "xmf/requests" / f"{cid}-xmf-disabled.json"
    dump(xreq_path, xreq)

    rreq = common_request(meta, owner_path, render_static, render_attempt, template, native=False)
    rreq.update({
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2,
        "max_wall_seconds": 7200, "estimated_storage_bytes": 34359738368,
        "command": ["/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython",
                    str(render_worker), "--manifest", "{xmf_attempt_root}/xdmf/manifest.json",
                    "--output-dir", "{attempt_root}/render"],
        "cwd": str(HERE),
        "depends_on_attempts": [typed_attempt, native_attempt, xmf_attempt],
        "xmf_attempt": xmf_attempt,
        "xmf_binding": str(xmf_binding_path), "xmf_binding_sha256": sha(xmf_binding_path),
        "xmf_case": str(xmf_case), "xmf_case_sha256": None,
        "xmf_manifest": str(xmf_manifest), "xmf_manifest_sha256": None,
        "typed_receipt": str(typed_receipt), "typed_receipt_sha256": None,
        "native_receipt": str(native_receipt), "native_receipt_sha256": None,
        "conversion_report": str(conversion_report), "conversion_report_sha256": None,
        "trajectory_h5": str(trajectory_h5), "trajectory_h5_sha256": None,
        "expected_dimension": 3, "expected_native_frames": 401, "expected_particles": None,
        "expected_native_contract": expected_contract,
        "camera_policy": render_binding["camera_policy"],
        "future_input_files": future_render_files,
        "future_input_sha256": future_render_sha,
        "future_outputs": render_binding["future_outputs"],
        "output_contract": {"execution_receipt_sha256": None, "report_sha256": None,
                            "frames_sha256": None, "actual_frame_count": None},
        "disabled_reason": "Enable only after Root reviews actual XMF manifest and keeps the full 401-frame native geometry path.",
    })
    rreq_path = HERE / "render/requests" / f"{cid}-render-disabled.json"
    dump(rreq_path, rreq)

    return {
        "case_id": cid,
        "physical_case_id": meta["physical_case_id"],
        "source_plan_physical_condition_sha256": source_plan,
        "prospective_legacy_scope_sha256": legacy_scope,
        "canonical_physical_binding_sha256": None,
        "typed_request": bind(typed_request_path),
        "xmf_binding": bind(xmf_binding_path),
        "xmf_request": bind(xreq_path),
        "render_binding": bind(render_binding_path),
        "render_request": bind(rreq_path),
        "expected_frames": 401,
        "expected_particles": None,
        "actual_typed_receipt": None,
        "actual_h5_sha256": None,
        "actual_xmf_sha256": None,
        "actual_render_sha256": None,
        "independent_case_count_increment": 0,
    }


def main() -> int:
    if not MANIFEST100.is_file():
        raise SystemExit(f"missing fresh100 manifest: {MANIFEST100}")
    manifest100 = read_json(MANIFEST100)
    if manifest100.get("fresh_id") != "fresh100" or manifest100.get("case_count") != 16:
        raise SystemExit("fresh100 manifest is not the expected 16-case source package")
    rows = manifest100["cases"]
    template = read_json(Path(rows[0]["requests"]["typed"]["path"]))
    # fresh100 predates the strict-dispatch input closure.  Fresh101 carries
    # the verified Root306/309 guard digest explicitly and binds the runtime,
    # strict-dispatch, Root142 policy, and resource approval below.
    template["strict_guard_digest"] = STRICT_GUARD_DIGEST
    preflight_rows = []
    for source_row in sorted(rows, key=lambda item: item["case_id"]):
        source_meta = read_json(Path(source_row["metadata"]["path"]))
        source_owner = read_json(Path(source_row["owner"]["path"]))
        preflight_rows.append({
            "case_id": source_row["case_id"],
            "source_plan_physical_condition_sha256": source_meta["source_plan_physical_condition_sha256"],
            "prospective_legacy_scope_sha256": source_owner["typed_scope_contract"]["prospective_legacy_scope_sha256"],
            "actual_converter_physical_condition_sha256": None,
            "canonical_physical_binding_sha256": None,
            "typed_receipt_sha256": None,
            "trajectory_h5_sha256": None,
        })
    dump(HERE / "metadata/legacy-scope-preflight.json", {
        "schema": "ds02.f2.stage1.fresh101.legacy-scope-preflight.v1",
        "source_only": True, "actual_conversion_executed": False,
        "scientific_inputs_opened": [], "canonical_scope_granted": False,
        "contract": "fresh100 typed_scope_contract prospective legacy-owner-scope.v0",
        "cases": preflight_rows,
    })
    dump(HERE / "metadata/contracts/xmf-contract.json", {
        "schema": "ds02.f2.stage1.fresh101.xmf-contract.v1",
        "worker": str((HERE / "workers/export_xmf.py").resolve()),
        "worker_sha256": sha(HERE / "workers/export_xmf.py"),
        "producer_scope_schema": "legacy-owner-scope.v0",
        "expected_frames": 401, "expected_dimension": 3,
        "expected_particles": None,
        "counts_source": "actual conversion-report only",
        "dynamic_vector_dimensions": "{actual_particles} 3",
        "dynamic_scalar_dimensions": "{actual_particles}",
        "output_dir": "{attempt_root}/xdmf",
        "output_dir_must_start_empty": True,
        "raw_metadata_only": True,
        "future_output_hashes_null": True,
    })
    dump(HERE / "metadata/contracts/render-contract.json", {
        "schema": "ds02.f2.stage1.fresh101.render-contract.v1",
        "worker": str((HERE / "workers/render_native023.py").resolve()),
        "worker_sha256": sha(HERE / "workers/render_native023.py"),
        "renderer": "Root023 CPU-only offscreen ParaView worker",
        "expected_frames": 401, "expected_dimension": 3,
        "camera_bounds_policy": {
            "bounds_source": "Root023 scans every native valid position across every saved frame",
            "camera_bounds_in_manifest": False, "domain_bounds_in_manifest": False,
            "fixed_camera_override": False, "native_geometry_retained": True,
        },
        "output_dir": "{attempt_root}/render",
        "output_dir_must_start_empty": True,
        "raw_metadata_only": True,
        "future_output_hashes_null": True,
    })
    dump(HERE / "metadata/contracts/typed-conversion-contract.json", {
        "schema": "ds02.f2.stage1.fresh101.typed-conversion-contract.v1",
        "converter": str(NVME), "direct_reader": str(DIRECT),
        "producer_scope_schema": "legacy-owner-scope.v0",
        "source_plan_and_legacy_scope_separate": True,
        "canonical_grant": False, "actual_converter_hashes": None,
        "typed_receipts": None, "trajectory_h5_hashes": None,
        "expected_frames": 401, "expected_dimension": 3,
        "resource_contract": RESOURCE_CONTRACT,
        "no_scientific_array_read_by_source_preparer": True,
    })
    dump(HERE / "metadata/contracts/runtime-strict-guard.json", {
        "schema": "ds02.f2.stage1.fresh101.runtime-strict-guard.v1",
        "strict_guard_digest": template["strict_guard_digest"],
        "runtime": str(RUNTIME), "runtime_sha256": sha(RUNTIME),
        "strict_dispatch": str(STRICT), "strict_dispatch_sha256": sha(STRICT),
        "worktree_root": str(INFRA), "source_only": True,
        "metadata_input_closure": "JSON/XML/Python/text only; no .dat, HDF5, BI4, CSV, or XMF in static input hashes",
        "future_payload_hashes": "null until Root-owned producer receipts exist",
    })
    dump(HERE / "metadata/base-binary-contract.json", {
        "schema": "ds02.f2.stage1.fresh101.base-binary-contract.v1",
        "root023_renderer": "/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython",
        "partvtk_decoder": "Root producer metadata only; no source-side scientific payload read",
        "native_recipe": {"frames": 401, "save_interval_s": 0.01, "window_s": [0.0, 4.0], "dimension": 3},
        "root_owned": True, "disabled": True,
    })
    generated = [make_case(row, template) for row in sorted(rows, key=lambda item: item["case_id"])]
    dump(HERE / "evidence/source-entry-audit.json", {
        "schema": "ds02.f2.stage1.fresh101.source-entry-audit.v1",
        "fresh100_immutable": True, "case_count": len(generated),
        "xmf_requests": len(generated), "render_requests": len(generated),
        "all_requests_disabled": True, "future_hashes_null": True,
        "static_input_suffixes": sorted(STATIC_SUFFIXES),
        "static_scientific_payloads_opened": [],
        "motion_dat_read_or_hashed": False,
        "typed_h5_read_or_hashed": False,
        "native_bi4_csv_read_or_hashed": False,
        "xmf_contract": "legacy-aware actual typed report supplies frames/particles; dynamic N3 XDMF dimensions",
        "render_contract": "Root023 all-frame bounds scan; no fixed camera/domain bounds; native geometry retained",
        "scope": "source plan hash, prospective legacy-owner scope hash, actual converter scope, and H5 digest remain distinct",
        "strict_dispatch_inputs_bound": True,
        "strict_guard_digest": STRICT_GUARD_DIGEST,
        "strict_guard_inputs": [str(RUNTIME.resolve()), str(STRICT.resolve()),
                                 str(ROOT142.resolve()), str(RESOURCE.resolve())],
        "canonical_grant": False, "independent_case_count_increment": 0,
    })
    dump(HERE / "F2_STAGE1_FRESH101_TYPED401_XMF_RENDER_MANIFEST.json", {
        "schema": "ds02.f2.stage1.fresh101.typed401-xmf-render-manifest.v1",
        "fresh_id": "fresh101", "family_id": "F2", "scope_id": SCOPE,
        "source_only": True, "execution_allowed": False,
        "case_count": len(generated), "cases": generated,
        "expected_native_frames": 401, "expected_dimension": 3,
        "expected_particles": None,
        "producer_scope_schema": "legacy-owner-scope.v0",
        "source_plan_and_legacy_scope_separate": True,
        "canonical_physical_binding_sha256": None, "canonical_grant": False,
        "strict_guard_digest": STRICT_GUARD_DIGEST,
        "strict_dispatch_inputs_bound": True,
        "future_hashes_null": True, "all_requests_disabled": True,
        "no_science_arrays_read": True, "no_jobs_started": True,
        "no_shared_registry_write": True, "independent_case_count_increment": 0,
        "contracts": {
            "xmf": bind(HERE / "metadata/contracts/xmf-contract.json"),
            "render": bind(HERE / "metadata/contracts/render-contract.json"),
            "typed": bind(HERE / "metadata/contracts/typed-conversion-contract.json"),
            "strict": bind(HERE / "metadata/contracts/runtime-strict-guard.json"),
        },
        "workers": {
            "export_xmf": bind(HERE / "workers/export_xmf.py"),
            "render_native023": bind(HERE / "workers/render_native023.py"),
            "source_contract_validator": bind(HERE / "workers/fresh101_source_contract_validator.py"),
        },
    })
    (HERE / "README.md").write_text(
        """# F2 fresh101 typed401 XMF and Root023 render adapter

This source-only package provides one disabled XMF request and one disabled
Root023 full-animation render request for each of the 16 fresh100 physical
conditions.  It reuses the validated legacy-aware XMF exporter and Root023
renderer shape from Root306/309, while keeping each fresh100 source-plan hash,
prospective `legacy-owner-scope.v0` hash, future actual converter scope, and
future trajectory H5 digest separate.

The XMF worker is enabled only after Root has independently completed the
matching GenCase, native 401-frame run, initial QA, and typed conversion.  It
reads the actual conversion report to obtain the particle count and emits
dynamic N3 XDMF dimensions (`N 3` vectors and `N` scalars); it does not use a
source-side guessed count.  The Root023 worker then scans every saved native
frame for bounds and keeps the full native geometry.  No fixed camera or
domain bounds are supplied.

Fresh101 preparation read and hashed only JSON/XML/Python/text metadata.  It
did not read or hash motion `.dat`, BI4/CSV/HDF5/XMF scientific payloads and
did not execute GenCase, solver, converter, decoder, PartVTK, ParaView, or
modify the shared ledger/registry.  All future receipts, XMF/render outputs,
trajectory hashes, and actual converter scope hashes remain null.  This is a
derived downstream view for existing conditions and adds zero independent
cases or qualification/production approval.

Every disabled request carries the verified strict-dispatch guard digest and
hash-closed inputs for runtime_v2, strict_dispatch, the Root142/Root230 home
floor policy, the resource approval, and the relevant renderer/converter
contracts.  The source package does not rely on a later validator to fill
those guard inputs.
""", encoding="utf-8")
    print(json.dumps({"schema": "ds02.f2.stage1.fresh101.build-result.v1",
                      "package": str(HERE), "case_count": len(generated),
                      "xmf_requests": len(generated), "render_requests": len(generated),
                      "future_hashes_null": True, "source_only": True}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
