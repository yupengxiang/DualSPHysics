#!/usr/bin/env python3
"""Build the F4 fresh098 post-frame-0 handoff.

This builder is metadata-only. It reads JSON/XML/Python source and the
Root-owned JSON receipts/reports, but never opens or hashes BI4, H5, CSV, DAT,
VTK, or other scientific payloads. Root533 owns the typed conversion already
in progress; this package records its exact request/current receipt state and
prepares disabled XMF and Root023 render requests for a later independently
verified typed result.
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

FRESH097 = WORKTREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_097_stage1_f4_native_frame0_partvtk_vz_to_typed_v1"
ROOT530 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_actualnative514_frame0_rawMk_vz_QA_530"
ROOT531 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_frame0QA530_first1_then_CPUcap2_controller_531"
ROOT533 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_actualnative514_frame0QA530_full1201_typed_NVMe_533"
ROOT534 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_fulltyped533_first1_then_global_NVMe_cap2_controller_534"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT134 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134"
ROOT023 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023"
RESOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"

PYTHON = INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
CONVERTER = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_nvme_convert_v1.py"
DIRECT_CONVERTER = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
XMF_EXPORTER = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_repair_a_short51_actual_typed_bed_pipeline_105/workers/export_xmf.py"
RENDERER = ROOT023 / "render.py"
PV_PYTHON = Path("/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython")
ENV = Path("/usr/bin/env")
MESA_JSON = Path("/usr/share/glvnd/egl_vendor.d/50_mesa.json")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
ROOT230_ENTRY = ROOT230 / "launch.py"
ROOT230_HOME = ROOT230 / "root_native_home_floor_inventory_policy.py"
ROOT230_CONTRACT = ROOT230 / "source-policy-contract.json"
ROOT134_GPU = ROOT134 / "ds02_root_all_idle_gpu_policy_v2.py"

SCOPE = "root_followup_098_stage1_f4_root530_typed_xmf_render_v1"
RAW_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".vtp"}
STATIC_SUFFIXES = {"", ".10", ".json", ".jsonl", ".xml", ".py", ".md", ".txt", ".log", ".linux64"}
PARTVTK_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
DECODER_SHA = "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
CONVERTER_SHA = "b9904026a201ef271c5cb4a80a7707034a542e01883cece915abb30955c5bad3"
DIRECT_CONVERTER_SHA = "8ec204edb5ac20f2d83e2b9a3b5e70eb45cf1104fe0ee4bd8c3413a241c10ccd"
RENDERER_SHA = "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66"
XMF_EXPORTER_SHA = "d70184e700ee23c6812d3185f37890df0174718445744643822f70ca03bd4e85"


def load(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES:
        raise RuntimeError(f"scientific payload read refused: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def sha(path: Path) -> str:
    path = Path(path).resolve()
    suffix = path.suffix.lower()
    if suffix in RAW_SUFFIXES:
        raise RuntimeError(f"scientific payload hash refused: {path}")
    if suffix not in STATIC_SUFFIXES:
        raise RuntimeError(f"non-static input cannot be hashed: {path}")
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
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha(path)}


def unique(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = Path(path).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def high(region: dict[str, Any]) -> list[float]:
    return [float(a) + float(b) for a, b in zip(region["low_m"], region["size_m"])]


def camera_for(case_id: str, physical: dict[str, Any]) -> dict[str, Any]:
    geometry = physical["geometry"]
    drop, pool, tank = geometry["drop"], geometry["pool"], geometry["tank"]
    tank_low = [float(x) for x in tank["low_m"]]
    tank_high = high(tank)
    domain_low = [x - 0.12 for x in tank_low]
    domain_high = [tank_high[0] + 0.15, tank_high[1] + 0.15, tank_high[2] + 0.25]
    return {
        "schema": "ds02.f4.root023-native-valid-point-scan-camera.v1",
        "case_id": case_id,
        "family_id": "F4",
        "bounds_source": "Root023 scans every actual saved native frame; this source entry does not precompute scientific bounds",
        "camera_strategy": "Root023 camera_for_bounds; source geometry is never clipped to this metadata envelope",
        "manifest_or_xml_bounds_used_as_camera_input": False,
        "reader_remains_unclipped": True,
        "camera_margin": 1.12,
        "cutaway_fraction": 0.5,
        "view_size": [640, 480],
        "show_boundary_outline": True,
        "boundary_point_opacity": 0.30,
        "coordinate_frame": "DualSPHysics Cartesian (x,y,z)",
        "native_reader_policy": {
            "full_native_reader": True,
            "native_boundary_points_visible": True,
            "source_reader_unclipped": True,
            "bbox_is_not_source_geometry": True,
            "boundary_outline_bbox_preview_only": True,
            "display_cutaway_is_proxy_only": True,
        },
        "framing": {
            "drop_low_m": [float(x) for x in drop["low_m"]],
            "drop_high_m": high(drop),
            "pool_low_m": [float(x) for x in pool["low_m"]],
            "pool_high_m": high(pool),
            "physical_tank_low_m": tank_low,
            "physical_tank_high_m": tank_high,
            "definition_pointmin_m": domain_low,
            "definition_pointmax_m": domain_high,
        },
        "xml_defined_domain_bounds": [[domain_low[i], domain_high[i]] for i in range(3)],
        "xml_defined_physical_tank_bounds": [[tank_low[i], tank_high[i]] for i in range(3)],
        "views": ["isometric", "transverse_side"],
        "text_policy": {"actual_time_format": ".17g", "rounded_time_labels": False, "family_label": "F4 DROP FULL1201"},
    }


def contact_pages() -> dict[str, Any]:
    pages = []
    for page in range(51):
        start = page * 24
        end = min(1200, start + 23)
        pages.append({"key": f"all_frames_{page:03d}", "filename": f"all_frames_{page:03d}.png", "frame_start": start, "frame_end": end, "frame_count": end - start + 1})
    return {
        "schema": "ds02.f4.root023-contact-page-keys.v1",
        "family_id": "F4",
        "frames": 1201,
        "page_size": 24,
        "page_count": 51,
        "all_frames_required": True,
        "diagnostic_subselection_is_not_full_product": True,
        "frame_key_pattern": "frame_{frame:04d}.png",
        "pages": pages,
    }


def request_base(case_id: str, attempt_id: str, command: list[str], task: str, max_wall: int,
                 storage: int, inputs: list[Path], deferred: list[Path], expected: dict[str, Any],
                 disabled_reason: str) -> dict[str, Any]:
    inputs = unique(inputs)
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F4",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": task,
        "cpu_threads": 2,
        "max_wall_seconds": max_wall,
        "estimated_storage_bytes": storage,
        "cwd": str(INTEGRATION / "lagrangian-fluid-lab"),
        "worktree_root": str(WORKTREE),
        "command": command,
        "input_files": [str(path) for path in inputs],
        "input_sha256": {str(path): sha(path) for path in inputs},
        "deferred_input_files": [str(Path(path)) for path in deferred],
        "deferred_input_sha256": {str(Path(path)): None for path in deferred},
        "disabled": True,
        "execution_allowed": False,
        "launch": False,
        "launch_allowed": False,
        "launch_owner": "root",
        "source_only": True,
        "status": "source_only_disabled",
        "disabled_reason": disabled_reason,
        "independent_case_count_increment": 0,
        "root_review_required": True,
        "scope_id": SCOPE,
        "precision_status": "not_accepted",
        "production_approval": "none",
        "q_n_status": "not_assessed",
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
        "expected_outputs": expected,
    }


def source_cases() -> dict[str, tuple[Path, dict[str, Any], dict[str, Any]]]:
    result: dict[str, tuple[Path, dict[str, Any], dict[str, Any]]] = {}
    paths = sorted((FRESH097 / "metadata/bindings").glob("*.native-frame0-binding.json"))
    if len(paths) != 24:
        raise RuntimeError(f"fresh097 native bindings expected 24, found {len(paths)}")
    for path in paths:
        binding = load(path)
        case_id = str(binding["case_id"])
        typed_path = FRESH097 / "metadata/bindings" / f"{case_id}.typed-binding.json"
        typed = load(typed_path)
        if case_id in result:
            raise RuntimeError(f"duplicate case {case_id}")
        result[case_id] = (path.resolve(), binding, typed)
    return result


def root533_requests() -> dict[str, Path]:
    result: dict[str, Path] = {}
    paths = sorted(ROOT533.glob("*-typed-request.json"))
    if len(paths) != 24:
        raise RuntimeError(f"Root533 typed requests expected 24, found {len(paths)}")
    for path in paths:
        request = load(path)
        case_id = str(request["case_id"])
        if case_id in result:
            raise RuntimeError(f"duplicate Root533 case {case_id}")
        result[case_id] = path.resolve()
    return result


def root530_state(case_id: str) -> dict[str, Any]:
    root = DATA / "families/F4" / case_id
    receipt_matches = sorted(root.glob("*native-frame0-partvtk-vz-fresh097-root530/execution-receipt.json"))
    report_matches = sorted(root.glob("*native-frame0-partvtk-vz-fresh097-root530/audit/native-frame0-partvtk-vz-audit.json"))
    if len(receipt_matches) > 1 or len(report_matches) > 1:
        raise RuntimeError(f"multiple Root530 artifacts for {case_id}")
    receipt_path = receipt_matches[0].resolve() if receipt_matches else None
    report_path = report_matches[0].resolve() if report_matches else None
    receipt = load(receipt_path) if receipt_path else None
    report = load(report_path) if report_path else None
    report_case = report
    if report and isinstance(report.get("cases"), list):
        matches = [row for row in report["cases"] if isinstance(row, dict) and row.get("case_id") == case_id]
        if len(matches) != 1:
            raise RuntimeError(f"Root530 aggregate report has no unique case row for {case_id}")
        report_case = matches[0]
    complete = bool(receipt and receipt.get("status") == "completed" and receipt.get("returncode") == 0)
    passed = bool(complete and report_case and report_case.get("status") == "completed_pass" and report_case.get("pass") is True)
    summary: dict[str, Any] = {}
    if report_case:
        for key in ("status", "pass", "native_raw_mk_type_observed", "native_raw_velocity_observed", "actual_total_particles", "native_rows", "fluid_rows", "finite_rows", "unique_identity_count", "unique_coordinate_count", "native_3d_levels", "type_counts", "fluid_rows_by_mk", "frame0_count_lifecycle", "max_abs_velocity_error_m_per_s", "velocity_tolerance_m_per_s", "mass_rescaling", "q_n"):
            if key in report_case:
                summary[key] = report_case[key]
    return {
        "case_id": case_id,
        "status": "completed_pass" if passed else ("completed_failed" if complete else "WAIT"),
        "receipt": ref(receipt_path) if receipt_path else None,
        "report": ref(report_path) if report_path else None,
        "receipt_status": receipt.get("status") if receipt else "WAIT",
        "receipt_returncode": receipt.get("returncode") if receipt else None,
        "report_summary": summary,
        "raw_science_payload_read_by_builder": False,
    }


def root533_state(case_id: str, request_path: Path, request: dict[str, Any]) -> dict[str, Any]:
    attempt_id = str(request["attempt_id"])
    case_root = DATA / "families/F4" / case_id
    receipt_candidates = sorted(case_root.glob(f"{attempt_id}/execution-receipt.json"))
    if not receipt_candidates:
        receipt_candidates = sorted(case_root.glob(f"*{attempt_id}*/execution-receipt.json"))
    if len(receipt_candidates) > 1:
        raise RuntimeError(f"multiple Root533 receipts for {case_id}")
    receipt_path = receipt_candidates[0].resolve() if receipt_candidates else None
    receipt = load(receipt_path) if receipt_path else None
    status = str(receipt.get("status")) if receipt else "WAIT"
    returncode = receipt.get("returncode") if receipt else None
    complete = status == "completed" and returncode == 0
    predicted_root = case_root / attempt_id
    output_root = Path(str(receipt.get("output_root"))) if receipt and receipt.get("output_root") else predicted_root
    owner_path = Path(str(request["owner_metadata"])).resolve()
    return {
        "request": ref(request_path),
        "attempt_id": attempt_id,
        "request_status": request.get("status"),
        "request_execution_allowed": request.get("execution_allowed"),
        "request_cpu_threads": request.get("cpu_threads"),
        "request_storage_bytes": request.get("estimated_storage_bytes"),
        "request_command": request.get("command"),
        "receipt": ref(receipt_path) if receipt_path else None,
        "receipt_status": status,
        "receipt_returncode": returncode,
        "typed_execution_status": "completed/0" if complete else "WAIT",
        "typed_receipt_only": bool(complete),
        "output_root": str(output_root),
        "trajectory_h5": str(output_root / "trajectory.h5"),
        "conversion_report": str(output_root / "conversion-report.json"),
        "execution_receipt": str(output_root / "execution-receipt.json"),
        "owner_metadata": ref(owner_path),
        "physical_condition_sha256": request.get("physical_condition_sha256"),
        "source_owner_physical_condition_sha256": request.get("source_owner_physical_condition_sha256"),
        "actual_converter_physical_scope": request.get("actual_converter_physical_scope"),
        "future_typed_output_hashes": {"trajectory_h5": None, "conversion_report": None, "execution_receipt": None},
        "raw_science_payload_read_by_builder": False,
    }


def gencase_snapshot(native_binding: dict[str, Any], typed_binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "actual_particle_counts": native_binding["actual_particle_counts"],
        "actual_total_particles": native_binding["actual_total_particles"],
        "dimension": 3,
        "generated_xml": native_binding["generated_xml"],
        "generated_xml_sha256": native_binding["generated_xml_sha256"],
        "prepared_input_report": native_binding["prepared_input_report"],
        "gencase_receipt": native_binding["gencase_receipt"],
        "gencase_receipt_sha256": native_binding["gencase_receipt_sha256"],
        "source_owner": native_binding["source_owner"],
        "source_plan_condition_sha256": native_binding.get("source_plan_condition_sha256"),
        "native_recipe": typed_binding.get("native_solver", {}),
        "raw_science_payload_read_by_builder": False,
    }


def main() -> None:
    for directory in (PACKAGE / "bindings", PACKAGE / "requests", PACKAGE / "evidence", PACKAGE / "render", PACKAGE / "metadata"):
        directory.mkdir(parents=True, exist_ok=True)
    cases = source_cases()
    typed_requests = root533_requests()
    controller531 = ROOT531 / "controller-result.json"
    controller534 = ROOT534 / "batch-controller.py"
    controller_snapshot: dict[str, Any] = {
        "root530_controller": ref(controller531) if controller531.is_file() else None,
        "root533_controller_source": ref(controller534) if controller534.is_file() else None,
    }
    if controller531.is_file():
        c = load(controller531)
        controller_snapshot["root530_controller_summary"] = {k: c.get(k) for k in ("requested", "finished", "completed0", "pending_held", "status") if k in c}

    camera_index: dict[str, Any] = {}
    for case_id in sorted(cases):
        req = load(typed_requests[case_id])
        owner = load(Path(str(req["owner_metadata"])))
        physical = req.get("actual_converter_physical_scope") or owner.get("physical_binding") or owner
        if not isinstance(physical, dict) or "geometry" not in physical:
            raise RuntimeError(f"Root533 owner has no physical geometry: {case_id}")
        camera_index[case_id] = camera_for(case_id, physical)
    dump(PACKAGE / "render/camera-spec.json", {"schema": "ds02.f4.fresh098-camera-index.v1", "family_id": "F4", "cases": camera_index})
    dump(PACKAGE / "render/contact-page-keys.json", contact_pages())
    dump(PACKAGE / "render/n3-vector-spec.json", {"schema": "ds02.f4.root023-n3-vector-spec.v1", "field": "velocity", "attribute_type": "Vector", "semantic_type": "N3", "components": ["vx", "vy", "vz"], "coordinate_frame": "DualSPHysics Cartesian (x,y,z)", "preserve_all_native_fields": True})

    case_rows: list[dict[str, Any]] = []
    request_rows: list[dict[str, Any]] = []
    frame_rows: list[dict[str, Any]] = []
    typed_rows: list[dict[str, Any]] = []

    for case_id in sorted(cases):
        native_path, native_binding, source_typed_binding = cases[case_id]
        root533_path = typed_requests[case_id]
        root533_request = load(root533_path)
        root533 = root533_state(case_id, root533_path, root533_request)
        frame0 = root530_state(case_id)
        frame_rows.append(frame0)
        typed_rows.append({"case_id": case_id, **root533})
        owner_path = Path(str(root533_request["owner_metadata"])).resolve()
        physical = root533_request.get("actual_converter_physical_scope")
        if not isinstance(physical, dict) or "geometry" not in physical:
            physical = load(owner_path).get("physical_binding") or load(owner_path)
        if not isinstance(physical, dict) or "geometry" not in physical:
            raise RuntimeError(f"Root533 owner has no physical geometry: {case_id}")
        if root533_request.get("physical_condition_sha256") == root533_request.get("source_owner_physical_condition_sha256"):
            raise RuntimeError(f"converter scope reused source owner hash: {case_id}")
        if int(root533_request.get("expected_particles", native_binding["actual_total_particles"])) != int(native_binding["actual_total_particles"]):
            raise RuntimeError(f"Root533 particle contract drift: {case_id}")
        root514_request_path = Path(native_binding["root514_request"]["path"]).resolve()
        root514_request = load(root514_request_path)
        source_owner_path = Path(native_binding["source_owner"]["path"]).resolve()
        gencase = gencase_snapshot(native_binding, source_typed_binding)
        physical_source = native_binding.get("physical_condition_sha256")
        actual_scope = {
            "schema": root533_request.get("actual_converter_physical_scope", {}).get("schema"),
            "legacy_scope_hash": root533_request.get("physical_condition_sha256"),
            "source_owner_physical_condition_sha256": root533_request.get("source_owner_physical_condition_sha256"),
            "source_physical_condition_sha256": physical_source,
            "source_plan_condition_sha256": native_binding.get("source_plan_condition_sha256"),
            "owner_metadata": ref(owner_path),
            "source_owner": ref(source_owner_path),
            "semantic_binding_status": root533_request.get("actual_converter_physical_scope", {}).get("semantic_binding_status", "legacy scope only; no canonical cross-resolution claim"),
            "source_owner_sha256_must_not_be_reused_as_converter_scope": True,
        }

        typed_output_root = Path(root533["output_root"])
        typed_output = {
            "attempt_id": root533["attempt_id"],
            "output_root": str(typed_output_root),
            "trajectory_h5": root533["trajectory_h5"],
            "conversion_report": root533["conversion_report"],
            "execution_receipt": root533["execution_receipt"],
            "execution_status": root533["typed_execution_status"],
            "trajectory_h5_sha256": None,
            "conversion_report_sha256": None,
            "execution_receipt_sha256": None,
            "actual_typed_frames": None,
            "actual_typed_particles": None,
            "actual_typed_fluid_particles": None,
            "actual_partvtk_all_passed": None,
            "integrity_status": "WAIT_for_root533_conversion_report_and_full_frame_count",
        }

        common = {
            "case_id": case_id,
            "physical_case_id": case_id,
            "physical_condition_sha256": root533_request.get("physical_condition_sha256"),
            "source_owner_physical_condition_sha256": root533_request.get("source_owner_physical_condition_sha256"),
            "physical_binding": physical,
            "source_physical_condition_sha256": physical_source,
            "source_plan_condition_sha256": native_binding.get("source_plan_condition_sha256"),
            "actual_converter_scope": actual_scope,
            "source_owner": ref(source_owner_path),
            "actual_owner_metadata": ref(owner_path),
            "gencase_actual_evidence": gencase,
            "root530_frame0_audit": frame0,
            "root533_typed_execution": root533,
            "root514_native_recipe": root514_request.get("solver_recipe", {"time_max_s": 1.2, "time_out_s": 0.001, "native_frame_count": 1201}),
            "native_frame0_binding": ref(native_path),
            "native_frame0_report_is_root530_observed": frame0["status"] == "completed_pass",
            "arrays_read_by_source": False,
            "jobs_started_by_source": False,
            "shared_registry_write_by_source": False,
            "precision_status": "not_accepted",
            "production_approval": "none",
            "q_n_status": "not_assessed",
        }

        typed_binding_path = PACKAGE / "bindings" / f"{case_id}-typed-binding.json"
        xmf_binding_path = PACKAGE / "bindings" / f"{case_id}-xmf-binding.json"
        render_binding_path = PACKAGE / "bindings" / f"{case_id}-render-binding.json"
        xmf_root = DATA / "families/F4" / case_id / f"root-stage1-f4-{case_id.lower()}-full1201-xmf-fresh098"
        render_root = DATA / "families/F4" / case_id / f"root-stage1-f4-{case_id.lower()}-full1201-render-fresh098"

        typed_binding = {
            "schema": "ds02.f4.fresh098.typed-result-binding.v1",
            "fresh_id": "fresh098",
            "scope_id": SCOPE,
            **common,
            "root533_request": ref(root533_path),
            "root533_receipt": root533["receipt"],
            "typed_output": typed_output,
            "typed_stage_owned_by": "Root533/Root534; this package does not duplicate or launch conversion",
            "typed_converter": {"script": str(CONVERTER), "script_sha256": CONVERTER_SHA, "direct_converter": str(DIRECT_CONVERTER), "direct_converter_sha256": DIRECT_CONVERTER_SHA, "official_partvtk": str(PARTVTK), "official_partvtk_sha256": PARTVTK_SHA, "official_decoder": str(DECODER), "official_decoder_sha256": DECODER_SHA, "cpu_threads": root533_request.get("cpu_threads", 4), "nvme_peak_bytes": root533_request.get("estimated_storage_bytes", 25769803776), "conversion_concurrency_cap": 2},
            "expected_native": {"frames": 1201, "time_window_s": 1.2, "save_interval_s": 0.001, "particles": native_binding["actual_total_particles"], "fluid_particles": native_binding["actual_particle_counts"]["fluid"], "dimension": 3},
            "actual_typed_counts": None,
            "vector_contract": {"velocity_field": "velocity", "semantic_type": "N3", "components": ["vx", "vy", "vz"], "coordinate_frame": "DualSPHysics Cartesian (x,y,z)"},
            "future_output_hashes": {"trajectory_h5": None, "conversion_report": None, "execution_receipt": None},
        }
        dump(typed_binding_path, typed_binding)

        xmf_binding = {
            "schema": "ds02.f4.fresh098.temporal-xmf-binding.v1",
            "fresh_id": "fresh098",
            "scope_id": SCOPE,
            **common,
            "typed_request": ref(root533_path),
            "typed_binding": ref(typed_binding_path),
            "typed_receipt": typed_output["execution_receipt"],
            "trajectory_h5": typed_output["trajectory_h5"],
            "conversion_report": typed_output["conversion_report"],
            "native_receipt": native_binding["native_solver_receipt"],
            "expected_frames": 1201,
            "expected_particles": native_binding["actual_total_particles"],
            "fluid_particles_expected": native_binding["actual_particle_counts"]["fluid"],
            "expected_dimension": 3,
            "physical_window_s": [0.0, 1.2],
            "camera_spec": str(PACKAGE / "render/camera-spec.json"),
            "contact_page_keys": str(PACKAGE / "render/contact-page-keys.json"),
            "camera_bounds_policy": {"source": "Root023 native valid point scan", "scan_all_saved_frames": True, "manifest_or_xml_bounds_used_as_camera_input": False, "reader_remains_unclipped": True},
            "source_xml_provenance": {"path": native_binding["generated_xml"], "producer_sha256": native_binding["generated_xml_sha256"], "role": "generated XML provenance; no scientific payload read by this source builder"},
            "type_aliases": {"fixed": [0], "moving": [1], "floating": [2], "fluid": [3]},
            "boundary_type_codes": [0],
            "finite_fields": ["mass", "velocity", "density", "pressure"],
            "vector_contract": {"velocity_field": "velocity", "attribute_type": "Vector", "semantic_type": "N3", "components": ["vx", "vy", "vz"]},
            "typed_gate": {"status": "WAIT", "requires_root533_receipt_completed0": True, "requires_conversion_report_full_frames": 1201, "requires_typed_h5_particle_count": native_binding["actual_total_particles"], "receipt_only_is_insufficient": True},
            "future_output_hashes": {"trajectory_h5": None, "conversion_report": None, "typed_receipt": None, "case_xmf": None, "manifest": None, "xmf_receipt": None},
        }
        dump(xmf_binding_path, xmf_binding)

        camera = camera_index[case_id]
        render_binding = {
            "schema": "ds02.f4.fresh098.root023-render-binding.v1",
            "fresh_id": "fresh098",
            "scope_id": SCOPE,
            **common,
            "typed_binding": ref(typed_binding_path),
            "xmf_binding": ref(xmf_binding_path),
            "camera_spec": str(PACKAGE / "render/camera-spec.json"),
            "contact_page_keys": str(PACKAGE / "render/contact-page-keys.json"),
            "vector_spec": str(PACKAGE / "render/n3-vector-spec.json"),
            "camera_contract": camera,
            "native_reader_policy": camera["native_reader_policy"],
            "typed_outputs_required_before_render": {"trajectory_h5": typed_output["trajectory_h5"], "conversion_report": typed_output["conversion_report"], "typed_receipt": typed_output["execution_receipt"], "all_sha256": None, "status": "deferred_until_root533_typed_completed0_and_audited"},
            "xmf_outputs_required_before_render": {"case_xmf": str(xmf_root / "case.xmf"), "manifest": str(xmf_root / "manifest.json"), "execution_receipt": str(xmf_root / "execution-receipt.json"), "all_sha256": None, "status": "deferred_until_xmf_completed0"},
            "expected_frames": 1201,
            "expected_particles": native_binding["actual_total_particles"],
            "fluid_particles_expected": native_binding["actual_particle_counts"]["fluid"],
            "expected_contact_pages": 51,
            "full_temporal_render_required": True,
            "type_aliases": {"fixed": [0], "moving": [1], "floating": [2], "fluid": [3]},
            "boundary_type_codes": [0],
            "finite_fields": ["mass", "velocity", "density", "pressure"],
            "vector_contract": {"velocity_field": "velocity", "semantic_type": "N3", "components": ["vx", "vy", "vz"], "all_native_fields": True},
            "future_output_hashes": {"case_pvsm": None, "contact_page": None, "execution_receipt": None, "gif": None, "report": None, "frame": None},
        }
        dump(render_binding_path, render_binding)

        static_common = [
            PYTHON, RUNTIME, STRICT, RESOURCE, ROOT230_ENTRY, ROOT230_HOME, ROOT230_CONTRACT, ROOT134_GPU,
            CONVERTER, DIRECT_CONVERTER, PARTVTK, DECODER, XMF_EXPORTER, RENDERER, ROOT023 / "README.md",
            root533_path, native_path, root514_request_path, source_owner_path, owner_path,
            Path(native_binding["generated_xml"]), Path(native_binding["prepared_input_report"]), Path(native_binding["gencase_receipt"]),
            Path(native_binding["native_solver_receipt"]), PACKAGE / "render/camera-spec.json", PACKAGE / "render/contact-page-keys.json", PACKAGE / "render/n3-vector-spec.json",
            typed_binding_path, xmf_binding_path, render_binding_path,
        ]
        if frame0["receipt"]:
            static_common.append(Path(frame0["receipt"]["path"]))
        if frame0["report"]:
            static_common.append(Path(frame0["report"]["path"]))
        if controller531.is_file():
            static_common.append(controller531)
        if controller534.is_file():
            static_common.append(controller534)
        static_common = unique(static_common)

        xmf_attempt = f"root-stage1-f4-{case_id.lower()}-full1201-xmf-fresh098"
        render_attempt = f"root-stage1-f4-{case_id.lower()}-full1201-render-fresh098"
        xmf_request_path = PACKAGE / "requests" / f"{case_id}-full1201-xmf-fresh098-disabled.request.json"
        render_request_path = PACKAGE / "requests" / f"{case_id}-full1201-render-fresh098-disabled.request.json"
        xmf_deferred = [Path(typed_output["trajectory_h5"]), Path(typed_output["conversion_report"]), Path(typed_output["execution_receipt"]), xmf_root / "case.xmf", xmf_root / "manifest.json", xmf_root / "execution-receipt.json"]
        xmf_command = [str(PYTHON), str(XMF_EXPORTER), "--binding", str(xmf_binding_path), "--output-dir", "{attempt_root}"]
        xmf_request = request_base(case_id, xmf_attempt, xmf_command, "conversion", 1800, 2 * 1024 ** 3, static_common, xmf_deferred, {"output_root": str(xmf_root), "case_xmf": str(xmf_root / "case.xmf"), "manifest": str(xmf_root / "manifest.json"), "execution_receipt": str(xmf_root / "execution-receipt.json"), "all_sha256": None}, "Root must first independently settle Root533 typed conversion as completed/0, verify the conversion report has all 1201 frames and the expected 3-D particle count, then enable this XMF sidecar. This source package does not substitute receipt-only evidence.")
        xmf_request.update({"physical_case_id": case_id, "physical_condition_sha256": root533_request.get("physical_condition_sha256"), "source_owner_physical_condition_sha256": root533_request.get("source_owner_physical_condition_sha256"), "typed_binding": ref(typed_binding_path), "xmf_binding": ref(xmf_binding_path), "native_frame0_audit": frame0, "root533_typed_snapshot": root533, "expected_frames": 1201, "expected_particles": native_binding["actual_total_particles"], "physical_window_s": [0.0, 1.2], "vector_semantic_type": "N3", "future_sha256_values": "null until Root completes and audits Root533/XMF", "typed_stage_is_not_relaunched": True})
        dump(xmf_request_path, xmf_request)

        render_deferred = [xmf_root / "case.xmf", xmf_root / "manifest.json", xmf_root / "execution-receipt.json", Path(typed_output["trajectory_h5"]), Path(typed_output["conversion_report"]), Path(typed_output["execution_receipt"]), render_root / "case.pvsm", render_root / "full_saved_animation.gif", render_root / "paraview-full-animation-report.json", render_root / "execution-receipt.json"]
        render_command = [str(ENV), "VTK_SMP_MAX_THREADS=2", "LP_NUM_THREADS=2", "LIBGL_ALWAYS_SOFTWARE=1", "MESA_LOADER_DRIVER_OVERRIDE=llvmpipe", "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json", "VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow", "QT_QPA_PLATFORM=offscreen", "OMP_NUM_THREADS=2", str(PV_PYTHON), "--force-offscreen-rendering", str(RENDERER), "--manifest", str(xmf_root / "manifest.json"), "--output-dir", "{attempt_root}"]
        render_inputs = unique(static_common + [ENV, MESA_JSON, PV_PYTHON])
        render_request = request_base(case_id, render_attempt, render_command, "audit", 14400, 12 * 1024 ** 3, render_inputs, render_deferred, {"output_root": str(render_root), "case_pvsm": str(render_root / "case.pvsm"), "full_saved_animation_gif": str(render_root / "full_saved_animation.gif"), "report": str(render_root / "paraview-full-animation-report.json"), "execution_receipt": str(render_root / "execution-receipt.json"), "all_sha256": None}, "Root must enable only after Root533 typed conversion and this package's XMF export are independently completed/0. Root023 must inspect all 1201 frames with the native reader; no diagnostic-frame shortcut is permitted.")
        render_request.update({"physical_case_id": case_id, "physical_condition_sha256": root533_request.get("physical_condition_sha256"), "source_owner_physical_condition_sha256": root533_request.get("source_owner_physical_condition_sha256"), "typed_binding": ref(typed_binding_path), "xmf_binding": ref(xmf_binding_path), "render_binding": ref(render_binding_path), "native_frame0_audit": frame0, "root533_typed_snapshot": root533, "expected_frames": 1201, "expected_particles": native_binding["actual_total_particles"], "expected_contact_pages": 51, "vector_semantic_type": "N3", "future_sha256_values": "null until Root completes typed/XMF/render", "typed_stage_is_not_relaunched": True})
        dump(render_request_path, render_request)

        request_rows.extend([
            {"case_id": case_id, "kind": "xmf", "path": str(xmf_request_path), "sha256": sha(xmf_request_path), "launch_allowed": False},
            {"case_id": case_id, "kind": "render", "path": str(render_request_path), "sha256": sha(render_request_path), "launch_allowed": False},
        ])
        case_rows.append({"case_id": case_id, "physical_case_id": case_id, "source_physical_condition_sha256": physical_source, "actual_converter_scope_sha256": root533_request.get("physical_condition_sha256"), "source_owner_physical_condition_sha256": root533_request.get("source_owner_physical_condition_sha256"), "frame0_status": frame0["status"], "typed_status": root533["typed_execution_status"], "typed_receipt_only": root533["typed_receipt_only"], "typed_binding": str(typed_binding_path), "xmf_request": str(xmf_request_path), "render_request": str(render_request_path), "typed_output_hash": None, "xmf_output_hash": None, "render_output_hash": None})

    dump(PACKAGE / "evidence/root530-frame0-snapshot.json", {"schema": "ds02.f4.root530-frame0-json-evidence.v1", "claim_boundary": "Root530 official PartVTK JSON reports are observed evidence only; no scientific CSV/BI4 was read or hashed by this source builder.", "controller": controller_snapshot, "cases": frame_rows, "arrays_read_by_source": False, "jobs_started_by_source": False})
    dump(PACKAGE / "evidence/root533-typed-snapshot.json", {"schema": "ds02.f4.root533-typed-json-evidence.v1", "claim_boundary": "Root533 requests and current JSON receipt states are recorded without relaunching conversion. Receipt completed/0 alone does not certify H5 frame/particle completeness; all future product hashes remain null.", "controller_source": ref(controller534) if controller534.is_file() else None, "cases": typed_rows, "arrays_read_by_source": False, "jobs_started_by_source": False})
    dump(PACKAGE / "metadata/physical-scope-contract.json", {"schema": "ds02.f4.fresh098-physical-scope-separation.v1", "source_condition_is_distinct_from_converter_scope": True, "source_owner_hash_must_not_be_reused": True, "converter_scope_source": "Root533 request physical_condition_sha256 and actual_converter_physical_scope; source owner condition is retained separately", "canonical_status": "not_accepted", "legacy_scope_status": "actual Root533 scope only; no cross-resolution or Q-N claim"})
    dump(PACKAGE / "requests/index.json", {"schema": "ds02.f4.fresh098-request-index.v1", "scope_id": SCOPE, "family_id": "F4", "launch_allowed": False, "independent_case_count_increment": 0, "typed_stage": "Root533-owned; not duplicated here", "request_count": len(request_rows), "requests": request_rows})
    dump(PACKAGE / "source-binding.json", {"schema": "ds02.f4.fresh098-source-binding.v1", "scope_id": SCOPE, "family_id": "F4", "claim_boundary": "Binds all 24 Root530 frame-0 JSON reports and Root533 typed request/receipt states. Only XMF and Root023 render are prepared here, both disabled; typed/H5/XMF/render hashes stay null until Root verifies each stage.", "case_count": len(case_rows), "independent_case_count_increment": 0, "root530_evidence": str(PACKAGE / "evidence/root530-frame0-snapshot.json"), "root533_evidence": str(PACKAGE / "evidence/root533-typed-snapshot.json"), "requests": request_rows, "cases": case_rows, "resource_window": ref(RESOURCE), "root230_policy": {"entry": ref(ROOT230_ENTRY), "home_policy": ref(ROOT230_HOME), "contract": ref(ROOT230_CONTRACT), "gpu_policy": ref(ROOT134_GPU), "home_free_gib_floor": 500, "nvme_free_gib_floor": 100, "nvme_peak_gib": 24, "conversion_concurrency_cap": 2}, "arrays_read_by_source": False, "jobs_started_by_source": False, "shared_registry_write_by_source": False})
    print(json.dumps({"package": str(PACKAGE), "case_count": len(case_rows), "request_count": len(request_rows), "frame0_completed_pass": sum(row["frame0_status"] == "completed_pass" for row in case_rows), "typed_completed0_receipt_only": sum(row["typed_status"] == "completed/0" for row in case_rows), "arrays_read_by_source": False, "jobs_started_by_source": False}, indent=2))


if __name__ == "__main__":
    main()
