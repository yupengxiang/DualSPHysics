#!/usr/bin/env python3
"""Build the F4 Root242 post-native typed/XMF/render handoff.

This builder is metadata-only. It reads JSON receipts and source metadata,
never opens BI4/H5/VTK/CSV scientific data, and emits disabled CPU requests.
The native solver receipt is evidence that Root242 exited 0; it is not evidence
that a typed timeline, XMF, or rendered product has been produced.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
for _parent in Path(__file__).resolve().parents:
    if (_parent / "AGENTS.md").is_file():
        F4_ROOT = _parent
        break
else:  # pragma: no cover - the repository always has AGENTS.md
    raise RuntimeError("F4 worktree root not found")

INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SCOPE = "root_followup_090_stage1_f4_root242_typed_xmf_render_bind_v1"
S089 = F4_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_089_stage1_f4_root237_qa_full1201_bind_v1"
S087 = F4_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_087_stage1_drop_gap_lattice_aligned_fallback6_source_v1"

CASES = (
    ("F4_DROP_LATTICE_GAP0p19000_DP010", "0p19000", 0.190),
    ("F4_DROP_LATTICE_GAP0p20000_DP010", "0p20000", 0.200),
    ("F4_DROP_LATTICE_GAP0p21000_DP010", "0p21000", 0.210),
    ("F4_DROP_LATTICE_GAP0p23000_DP010", "0p23000", 0.230),
    ("F4_DROP_LATTICE_GAP0p24000_DP010", "0p24000", 0.240),
    ("F4_DROP_LATTICE_GAP0p25000_DP010", "0p25000", 0.250),
)

PYTHON = INTEGRATION_ROOT / "lagrangian-fluid-lab/.venv/bin/python"
CONVERTER = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_nvme_convert_v1.py"
DIRECT_CONVERTER = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
NVME_AUDIT = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_f3_nvme_input_audit_v1.py"
CONVERT = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_convert.py"
RUNTIME = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
GOAL = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
XMF_EXPORTER = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_repair_a_short51_actual_typed_bed_pipeline_105/workers/export_xmf.py"
RENDERER = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py"
PV_PYTHON = Path("/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython")
ENV = Path("/usr/bin/env")
MESA_JSON = Path("/usr/share/glvnd/egl_vendor.d/50_mesa.json")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
ROOT230_ENTRY = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py"
ROOT230_HOME = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230/root_native_home_floor_inventory_policy.py"
ROOT134_GPU = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
ROOT230_CONTRACT = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230/source-policy-contract.json"
RESOURCE_WINDOW = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
ROOT023_DIR = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023"

STATIC_HASHES = {
    # This mature binary hash is already recorded in the accepted F4 source
    # contract. The builder never scans the scientific output tree.
    str(PARTVTK): "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def sha(path: Path) -> str:
    if path.suffix.lower() in {".bi4", ".h5", ".hdf5", ".vtk", ".csv"}:
        raise RuntimeError(f"scientific array artifact must not be read by source builder: {path}")
    if str(path) in STATIC_HASHES:
        return STATIC_HASHES[str(path)]
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ref(path: Path, *, digest: str | None = None) -> dict[str, str]:
    return {"path": str(path), "sha256": digest if digest is not None else sha(path)}


def unique(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def camera_for(case_id: str, physical: dict[str, Any]) -> dict[str, Any]:
    geometry = physical["geometry"]
    drop = geometry["drop"]
    pool = geometry["pool"]
    tank = geometry["tank"]

    def high(region: dict[str, Any]) -> list[float]:
        return [float(a) + float(b) for a, b in zip(region["low_m"], region["size_m"])]

    tank_low = [float(x) for x in tank["low_m"]]
    tank_high = high(tank)
    domain_low = [x - 0.12 for x in tank_low]
    domain_high = [tank_high[0] + 0.15, tank_high[1] + 0.15, tank_high[2] + 0.25]
    return {
        "schema": "ds02.f4.drop-lattice-root023-native-valid-point-scan.v1",
        "case_id": case_id,
        "family_id": "F4",
        "bounds_source": "native valid positions scanned through Root023 XdmfReader across every actual saved frame",
        "camera_strategy": "Root023 camera_for_bounds; source geometry is never clipped to this metadata envelope",
        "camera_margin": 1.12,
        "cutaway_fraction": 0.5,
        "manifest_or_xml_bounds_used_as_camera_input": False,
        "reader_remains_unclipped": True,
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
        "view_size": [640, 480],
        "text_policy": {"actual_time_format": ".17g", "rounded_time_labels": False, "family_label": "F4 DROP LATTICE FULL1201"},
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


def base_request(case_id: str, attempt_id: str, command: list[str], *, task: str, max_wall: int,
                 storage: int, inputs: list[Path], deferred: list[Path], deferred_hashes: dict[str, str | None],
                 expected: dict[str, Any], disabled_reason: str) -> dict[str, Any]:
    inputs = unique(inputs)
    for path in inputs:
        if not path.is_file():
            raise RuntimeError(f"request input is not a regular file: {path}")
    hashes = {str(path): sha(path) for path in inputs}
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
        "cwd": str(INTEGRATION_ROOT / "lagrangian-fluid-lab"),
        "worktree_root": str(F4_ROOT),
        "command": command,
        "input_files": [str(path) for path in inputs],
        "input_sha256": hashes,
        "deferred_input_files": [str(path) for path in deferred],
        "deferred_input_sha256": deferred_hashes,
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
        "expected_outputs": expected,
    }


def main() -> None:
    (PACKAGE / "bindings").mkdir(parents=True, exist_ok=True)
    (PACKAGE / "requests").mkdir(parents=True, exist_ok=True)
    (PACKAGE / "evidence").mkdir(parents=True, exist_ok=True)
    (PACKAGE / "render").mkdir(parents=True, exist_ok=True)

    camera_map: dict[str, Any] = {}
    native_rows: list[dict[str, Any]] = []
    case_records: list[dict[str, Any]] = []
    all_requests: list[dict[str, Any]] = []
    source_binding = load(S089 / "source-binding.json")

    # These small metadata inputs must exist before request input digests are
    # assembled.  The same deterministic values are rewritten after the loop
    # once all case records have been collected.
    camera_map = {
        case_id: camera_for(case_id, load(S089 / "requests" / f"{case_id}-full1201-native-qualification.request.json")["physical_binding"])
        for case_id, _gap_label, _gap_m in CASES
    }
    dump(PACKAGE / "render" / "camera-spec.json", {"schema": "ds02.f4.root242-camera-spec-index.v1", "family_id": "F4", "camera_strategy": "Root023 full-state native valid-point scan", "cases": camera_map})
    dump(PACKAGE / "render" / "contact-page-keys.json", contact_pages())
    dump(PACKAGE / "render" / "n3-vector-spec.json", {"schema": "ds02.f4.root023-n3-vector-spec.v1", "field": "velocity", "attribute_type": "Vector", "semantic_type": "N3", "components": ["vx", "vy", "vz"], "coordinate_frame": "DualSPHysics Cartesian (x,y,z)", "preserve_all_native_fields": True})

    for case_id, _gap_label, gap_m in CASES:
        source_request_path = S089 / "requests" / f"{case_id}-full1201-native-qualification.request.json"
        source_request = load(source_request_path)
        actual_dirs = sorted((DATA_ROOT / "families" / "F4" / case_id).glob("*root230-089"))
        if len(actual_dirs) != 1:
            raise RuntimeError(f"expected one Root242 attempt for {case_id}, got {actual_dirs}")
        native_root = actual_dirs[0]
        native_receipt_path = native_root / "execution-receipt.json"
        native_receipt = load(native_receipt_path)
        if native_receipt.get("status") != "completed" or native_receipt.get("returncode") != 0:
            raise RuntimeError(f"Root242 native receipt is not completed/0 for {case_id}")
        native_request = native_receipt["request"]
        if native_request.get("attempt_id") != source_request["attempt_id"]:
            raise RuntimeError(f"Root242 changed source native attempt identity for {case_id}")
        if native_request.get("command", [])[-2:] != ["-tmax:1.2", "-tout:0.001"]:
            raise RuntimeError(f"Root242 solver recipe drift for {case_id}")

        gencase = source_request["gencase_actual_evidence"]
        qa = source_request["native_initial_qa"]
        physical = source_request["physical_binding"]
        source_manifest_path = S089 / "manifests" / f"{case_id}.json"
        source_manifest = load(source_manifest_path)
        source_row = next(row for row in source_binding["rows"] if row["endpoint_id"] == case_id)
        source_recipe = source_request["solver_recipe"]
        solver_output = Path(native_receipt["command"][3])
        data_root = solver_output / "data"
        run_out = solver_output / "Run.out"
        output_base = DATA_ROOT / "families" / "F4" / case_id
        typed_attempt = f"root-stage1-f4-{case_id.lower()}-full1201-typed-nvme-root242-090"
        xmf_attempt = f"root-stage1-f4-{case_id.lower()}-full1201-xmf-root242-090"
        render_attempt = f"root-stage1-f4-{case_id.lower()}-full1201-render-root242-090"
        typed_root = output_base / typed_attempt
        xmf_root = output_base / xmf_attempt
        render_root = output_base / render_attempt
        owner_path = Path(source_request["owner_binding"]["path"])
        metadata_path = Path(source_request["metadata_binding"]["path"])
        definition_path = next(Path(e["path"]) for e in source_manifest["entries"] if e["role"] == "source_definition")
        source_plan_path = next(Path(e["path"]) for e in source_manifest["entries"] if e["role"] == "source_plan")
        source_build_path = next(Path(e["path"]) for e in source_manifest["entries"] if e["role"] == "source_build_receipt")
        prepared_report_path = next(Path(e["path"]) for e in source_manifest["entries"] if e["role"] == "actual_prepared_input_report")
        source_binding_path = S089 / "source-binding.json"
        source_qa_index = Path(qa["index"])
        source_qa_binding = Path(qa["binding"])
        source_qa_receipt = Path(qa["execution_receipt"])
        source_qa_report = Path(qa["case_report"])
        source_qa_metadata = Path(qa["case_metadata"])
        gencase_receipt = Path(gencase["per_case_receipt"])
        xml_path = Path(gencase["generated_xml"]["path"])
        bi4_path = Path(gencase["generated_bi4"]["path"])
        source_qa_worker = S087 / "workers/run_f4_fallback_native_initial_qa_v1.py"

        camera = camera_for(case_id, physical)
        camera_map[case_id] = camera
        typed_binding_path = PACKAGE / "bindings" / f"{case_id}-typed-binding.json"
        xmf_binding_path = PACKAGE / "bindings" / f"{case_id}-xmf-binding.json"
        render_binding_path = PACKAGE / "bindings" / f"{case_id}-render-binding.json"
        camera_path = PACKAGE / "render" / "camera-spec.json"
        contact_path = PACKAGE / "render" / "contact-page-keys.json"
        vector_path = PACKAGE / "render" / "n3-vector-spec.json"

        native_ref = {
            "path": str(native_receipt_path),
            "sha256": sha(native_receipt_path),
            "status": native_receipt["status"],
            "returncode": native_receipt["returncode"],
            "attempt_id": native_receipt["request"]["attempt_id"],
            "request_sha256": native_receipt["request_sha256"],
            "source_request_path": str(source_request_path),
            "source_request_sha256": sha(source_request_path),
            "output_root": str(native_root),
            "bytes": native_receipt.get("bytes"),
            "elapsed_seconds": native_receipt.get("elapsed_seconds"),
            "started_at_utc": native_receipt.get("started_at_utc"),
            "finished_at_utc": native_receipt.get("finished_at_utc"),
            "gpu": native_receipt.get("gpu"),
            "cuda_visible_devices": native_receipt.get("cuda_visible_devices"),
            "solver_recipe": native_request.get("solver_recipe"),
            "physical_condition_sha256": native_request.get("physical_condition_sha256"),
            "source_plan_condition_sha256": native_request.get("source_plan_condition_sha256"),
        }

        native_rows.append({
            "case_id": case_id,
            "physical_case_id": source_request["physical_case_id"],
            "physical_condition_sha256": source_request["physical_condition_sha256"],
            "source_plan_condition_sha256": source_request["source_plan_condition_sha256"],
            "native_receipt": native_ref,
            "enabled_request": {
                "request_sha256": native_receipt["request_sha256"],
                "attempt_id": native_request["attempt_id"],
                "launch": native_request.get("launch"),
                "launch_allowed": native_request.get("launch_allowed"),
                "cwd": native_request.get("cwd"),
                "command": native_request.get("command"),
                "solver_recipe": native_request.get("solver_recipe"),
                "physical_condition_sha256": native_request.get("physical_condition_sha256"),
                "source_plan_condition_sha256": native_request.get("source_plan_condition_sha256"),
            },
        })

        source_common = {
            "case_id": case_id,
            "physical_case_id": source_request["physical_case_id"],
            "physical_binding": physical,
            "physical_condition_sha256": source_request["physical_condition_sha256"],
            "source_plan_condition_sha256": source_request["source_plan_condition_sha256"],
            "solver_recipe": source_recipe,
            "canonical_owner": ref(owner_path),
            "metadata": ref(metadata_path),
            "source_definition": ref(definition_path),
            "source_plan": ref(source_plan_path),
            "source_build_receipt": ref(source_build_path),
            "source_native_attempt_id": source_request["attempt_id"],
            "root242_native": native_ref,
            "gencase_actual": {
                **gencase,
                "generated_bi4": {**gencase["generated_bi4"], "source_read_by_builder": False},
                "generated_xml": {**gencase["generated_xml"], "source_read_by_builder": False},
            },
            "initial_native_qa_actual": {
                **qa,
                "source_read_by_builder": False,
                "raw_arrays_read_by_registered_qa_job": qa.get("raw_native_arrays", []),
            },
            "native_receipt_does_not_prove_typed_or_visual_completeness": True,
        }

        typed_output = {
            "attempt_id": typed_attempt,
            "output_root": str(typed_root),
            "trajectory_h5": str(typed_root / "trajectory.h5"),
            "conversion_report": str(typed_root / "conversion-report.json"),
            "execution_receipt": str(typed_root / "execution-receipt.json"),
            "trajectory_h5_sha256": None,
            "conversion_report_sha256": None,
            "execution_receipt_sha256": None,
            "actual_typed_frames": None,
            "actual_typed_particles": None,
            "actual_typed_fluid_particles": None,
            "actual_partvtk_all_passed": None,
        }
        typed_binding = {
            "schema": "ds02.f4.root242-typed-nvme-binding.v1",
            **source_common,
            "typed_output": typed_output,
            "typed_converter": {"script": str(CONVERTER), "direct_converter": str(DIRECT_CONVERTER), "input_audit": str(NVME_AUDIT), "staging_peak_limit_bytes": 25769803776, "nvme_free_floor_bytes": 107374182400, "conversion_concurrency_cap": 2, "source_h5_read_only": True, "particle_chunk": 65536},
            "expected_native_counts": {"total_particles": gencase["total_particles"], "fluid_particles": gencase["fluid_particles"], "fixed_particles": gencase["fixed_particles"], "dimension": gencase["solver_dimension_from_gencase"], "frames": source_recipe["native_frame_count"]},
            "actual_typed_counts": None,
            "vector_contract": {"velocity_field": "velocity", "semantic_type": "N3", "components": ["vx", "vy", "vz"], "coordinate_frame": "DualSPHysics Cartesian (x,y,z)"},
            "arrays_read_by_source": False,
            "jobs_started_by_source": False,
        }
        dump(typed_binding_path, typed_binding)

        xmf_binding = {
            "schema": "ds02.f4.root242-temporal-xmf-binding.v1",
            **source_common,
            "typed_receipt": typed_output["execution_receipt"],
            "trajectory_h5": typed_output["trajectory_h5"],
            "conversion_report": typed_output["conversion_report"],
            "native_receipt": str(native_receipt_path),
            "expected_frames": source_recipe["native_frame_count"],
            "expected_particles": gencase["total_particles"],
            "fluid_particles_expected": gencase["fluid_particles"],
            "expected_dimension": gencase["solver_dimension_from_gencase"],
            "physical_window_s": [0.0, source_recipe["time_max_s"]],
            "camera_spec": str(camera_path),
            "contact_page_keys": str(contact_path),
            "camera_bounds_policy": {"source": "native valid point scan", "scan_all_saved_frames": True, "manifest_or_xml_bounds_used_as_camera_input": False, "reader_remains_unclipped": True},
            "source_xml_provenance": {"path": str(xml_path), "producer_sha256": gencase["generated_xml"]["producer_sha256"], "role": "source XML metadata/provenance; no source-builder array read"},
            "vector_contract": {"velocity_field": "velocity", "attribute_type": "Vector", "semantic_type": "N3", "components": ["vx", "vy", "vz"]},
            "future_sha256_values": {"trajectory_h5": None, "conversion_report": None, "typed_receipt": None, "case_xmf": None, "manifest": None, "xmf_receipt": None},
            "actual_typed_counts": None,
            "arrays_read_by_source": False,
        }
        dump(xmf_binding_path, xmf_binding)

        render_binding = {
            "schema": "ds02.f4.root242-root023-full-state-render-binding.v1",
            **source_common,
            "xmf_binding": ref(xmf_binding_path),
            "camera_spec": str(camera_path),
            "contact_page_keys": str(contact_path),
            "vector_spec": str(vector_path),
            "camera_contract": camera,
            "native_reader_policy": camera["native_reader_policy"],
            "typed_outputs_required_before_render": {"trajectory_h5": typed_output["trajectory_h5"], "conversion_report": typed_output["conversion_report"], "typed_receipt": typed_output["execution_receipt"], "all_sha256": None, "status": "deferred_until_typed_completed0"},
            "xmf_outputs_required_before_render": {"case_xmf": str(xmf_root / "case.xmf"), "manifest": str(xmf_root / "manifest.json"), "execution_receipt": str(xmf_root / "execution-receipt.json"), "case_xmf_sha256": None, "manifest_sha256": None, "execution_receipt_sha256": None, "status": "deferred_until_xmf_completed0"},
            "expected_frames": source_recipe["native_frame_count"],
            "expected_particles": gencase["total_particles"],
            "fluid_particles_expected": gencase["fluid_particles"],
            "expected_contact_pages": 51,
            "full_temporal_render_required": True,
            "vector_contract": {"velocity_field": "velocity", "semantic_type": "N3", "components": ["vx", "vy", "vz"], "all_native_fields": True},
            "actual_typed_counts": None,
            "future_outputs": {"case_pvsm_sha256": None, "contact_page_sha256": None, "execution_receipt_sha256": None, "gif_sha256": None, "report_sha256": None, "frame_sha256": None},
            "arrays_read_by_source": False,
        }
        dump(render_binding_path, render_binding)

        common_source_inputs = [PYTHON, RUNTIME, STRICT, GOAL, owner_path, metadata_path, definition_path, source_plan_path, source_build_path, source_binding_path, source_manifest_path, source_request_path, gencase_receipt, prepared_report_path, source_qa_receipt, source_qa_index, source_qa_binding, source_qa_report, source_qa_metadata, native_receipt_path, ROOT230_ENTRY, ROOT230_HOME, ROOT134_GPU, ROOT230_CONTRACT, RESOURCE_WINDOW]
        typed_inputs = common_source_inputs + [CONVERTER, DIRECT_CONVERTER, NVME_AUDIT, CONVERT, PARTVTK, typed_binding_path]
        typed_deferred = [data_root, run_out, xml_path, bi4_path, typed_root / "trajectory.h5", typed_root / "conversion-report.json", typed_root / "execution-receipt.json"]
        typed_deferred_hashes = {str(xml_path): gencase["generated_xml"]["producer_sha256"], str(bi4_path): None, str(native_receipt_path): native_ref["sha256"], str(gencase_receipt): gencase["per_case_receipt_sha256"], str(typed_root / "trajectory.h5"): None, str(typed_root / "conversion-report.json"): None, str(typed_root / "execution-receipt.json"): None}
        typed_command = [str(PYTHON), str(CONVERTER), "--staging-root", "{attempt_root}/nvme-staging", "--staging-limit-bytes", "25769803776", "--", "--data-root", str(data_root), "--generated-xml", str(xml_path), "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json", "--decoder", str(DECODER), "--partvtk", str(PARTVTK), "--validation-dir", "{attempt_root}/partvtk-validation", "--solver-log", str(run_out), "--solver-receipt", str(native_receipt_path), "--gencase-receipt", str(gencase_receipt), "--owner-metadata", str(owner_path), "--keep-validation-csv", "--particle-chunk", "65536"]
        typed_request = base_request(case_id, typed_attempt, typed_command, task="conversion", max_wall=14400, storage=25769803776, inputs=typed_inputs, deferred=typed_deferred, deferred_hashes=typed_deferred_hashes, expected={"output_root": str(typed_root), "trajectory_h5": str(typed_root / "trajectory.h5"), "conversion_report": str(typed_root / "conversion-report.json"), "execution_receipt": str(typed_root / "execution-receipt.json"), "all_sha256": None}, disabled_reason="Root must enable only after reviewing the completed Root242 native receipt. This request still must independently validate opaque native input, PartVTK fields, native-to-NVME preservation, actual frame count, and typed output integrity.")
        typed_request.update({"physical_case_id": source_request["physical_case_id"], "physical_condition_sha256": source_request["physical_condition_sha256"], "source_plan_condition_sha256": source_request["source_plan_condition_sha256"], "native_receipt": native_ref, "gencase_actual_evidence": gencase, "native_initial_qa": qa, "solver_recipe": source_recipe, "output_contract": {"expected_native_frames": source_recipe["native_frame_count"], "expected_native_particles": gencase["total_particles"], "expected_native_fluid_particles": gencase["fluid_particles"], "actual_typed_frames": None, "actual_typed_particles": None, "actual_typed_fluid_particles": None, "partvtk_all_passed": None, "actual_time_s_preserved": True, "source_h5_read_only": True, "vector_semantic_type": "N3", "future_sha256_values": "null until Root completes this disabled request"}, "storage_contract": {"concurrency_cap": 2, "nvme_free_floor_bytes": 107374182400, "staging_peak_limit_bytes": 25769803776, "source_h5_read_only": True}, "typed_binding": ref(typed_binding_path), "source_native_attempt_id": source_request["attempt_id"], "source_native_request_sha256": sha(source_request_path), "root242_native_request_sha256": native_ref["request_sha256"], "root_actual_native_output_root": str(native_root), "arrays_read_by_source": False, "jobs_started_by_source": False})
        typed_request_path = PACKAGE / "requests" / f"{case_id}-full1201-typed-nvme.request.json"
        dump(typed_request_path, typed_request)
        all_requests.append({"case_id": case_id, "kind": "typed_nvme", "path": str(typed_request_path), "sha256": sha(typed_request_path), "launch_allowed": False})

        xmf_inputs = common_source_inputs + [XMF_EXPORTER, typed_binding_path, xmf_binding_path, camera_path, contact_path, vector_path]
        xmf_deferred = [Path(typed_output["trajectory_h5"]), Path(typed_output["conversion_report"]), Path(typed_output["execution_receipt"]), native_receipt_path, xmf_root / "case.xmf", xmf_root / "manifest.json", xmf_root / "execution-receipt.json"]
        xmf_hashes = {str(path): None for path in xmf_deferred}
        xmf_hashes[str(native_receipt_path)] = native_ref["sha256"]
        xmf_command = [str(PYTHON), str(XMF_EXPORTER), "--binding", str(xmf_binding_path), "--output-dir", "{attempt_root}"]
        xmf_request = base_request(case_id, xmf_attempt, xmf_command, task="conversion", max_wall=1800, storage=2 * 1024**3, inputs=xmf_inputs, deferred=xmf_deferred, deferred_hashes=xmf_hashes, expected={"output_root": str(xmf_root), "case_xmf": str(xmf_root / "case.xmf"), "manifest": str(xmf_root / "manifest.json"), "execution_receipt": str(xmf_root / "execution-receipt.json"), "all_sha256": None}, disabled_reason="Root must enable only after the independent typed conversion is completed/0 and its report verifies all native fields; the XMF producer must preserve all actual saved times and source HDF5 identity.")
        xmf_request.update({"physical_case_id": source_request["physical_case_id"], "physical_condition_sha256": source_request["physical_condition_sha256"], "source_plan_condition_sha256": source_request["source_plan_condition_sha256"], "xmf_binding": ref(xmf_binding_path), "typed_binding": ref(typed_binding_path), "native_receipt": native_ref, "solver_recipe": source_recipe, "output_contract": {"expected_native_frames": source_recipe["native_frame_count"], "expected_native_particles": gencase["total_particles"], "expected_native_fluid_particles": gencase["fluid_particles"], "actual_typed_frames": None, "actual_xmf_frames": None, "actual_time_source": "typed HDF5 time dataset after independent conversion", "xdmf_time_format": ".17g", "vector_semantic_type": "N3", "future_sha256_values": "null until Root completes this disabled request"}, "arrays_read_by_source": False, "jobs_started_by_source": False})
        xmf_request_path = PACKAGE / "requests" / f"{case_id}-full1201-xmf.request.json"
        dump(xmf_request_path, xmf_request)
        all_requests.append({"case_id": case_id, "kind": "xmf", "path": str(xmf_request_path), "sha256": sha(xmf_request_path), "launch_allowed": False})

        render_inputs = common_source_inputs + [ENV, MESA_JSON, PV_PYTHON, RENDERER, ROOT023_DIR / "README.md", typed_binding_path, xmf_binding_path, render_binding_path, camera_path, contact_path, vector_path]
        render_deferred = [xmf_root / "case.xmf", xmf_root / "manifest.json", xmf_root / "execution-receipt.json", Path(typed_output["trajectory_h5"]), Path(typed_output["conversion_report"]), Path(typed_output["execution_receipt"]), native_receipt_path, render_root / "case.pvsm", render_root / "full_saved_animation.gif", render_root / "paraview-full-animation-report.json", render_root / "execution-receipt.json"]
        render_hashes = {str(path): None for path in render_deferred}
        render_hashes[str(native_receipt_path)] = native_ref["sha256"]
        render_command = [str(ENV), "VTK_SMP_MAX_THREADS=2", "LP_NUM_THREADS=2", "LIBGL_ALWAYS_SOFTWARE=1", "MESA_LOADER_DRIVER_OVERRIDE=llvmpipe", "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json", "VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow", "QT_QPA_PLATFORM=offscreen", "OMP_NUM_THREADS=2", str(PV_PYTHON), "--force-offscreen-rendering", str(RENDERER), "--manifest", str(xmf_root / "manifest.json"), "--output-dir", "{attempt_root}"]
        render_request = base_request(case_id, render_attempt, render_command, task="audit", max_wall=14400, storage=12 * 1024**3, inputs=render_inputs, deferred=render_deferred, deferred_hashes=render_hashes, expected={"output_root": str(render_root), "case_pvsm": str(render_root / "case.pvsm"), "full_saved_animation_gif": str(render_root / "full_saved_animation.gif"), "report": str(render_root / "paraview-full-animation-report.json"), "execution_receipt": str(render_root / "execution-receipt.json"), "all_sha256": None}, disabled_reason="Root must enable only after typed conversion and XMF completed/0. Root023 must scan all 1201 frames, preserve native valid boundaries and N3 velocity vectors, and emit a full-state report; no diagnostic-frame shortcut is permitted.")
        render_request.update({"physical_case_id": source_request["physical_case_id"], "physical_condition_sha256": source_request["physical_condition_sha256"], "source_plan_condition_sha256": source_request["source_plan_condition_sha256"], "render_binding": ref(render_binding_path), "xmf_binding": ref(xmf_binding_path), "typed_binding": ref(typed_binding_path), "native_receipt": native_ref, "solver_recipe": source_recipe, "output_contract": {"expected_native_frames": source_recipe["native_frame_count"], "expected_native_particles": gencase["total_particles"], "expected_native_fluid_particles": gencase["fluid_particles"], "actual_xmf_frames": None, "actual_rendered_frames": None, "expected_contact_pages": 51, "full_temporal_render_required": True, "native_geometry_visible": True, "vector_semantic_type": "N3", "future_sha256_values": "null until Root completes this disabled request"}, "arrays_read_by_source": False, "jobs_started_by_source": False})
        render_request_path = PACKAGE / "requests" / f"{case_id}-full1201-render.request.json"
        dump(render_request_path, render_request)
        all_requests.append({"case_id": case_id, "kind": "render", "path": str(render_request_path), "sha256": sha(render_request_path), "launch_allowed": False})

        case_records.append({"case_id": case_id, "gap_m": gap_m, "physical_case_id": source_request["physical_case_id"], "physical_condition_sha256": source_request["physical_condition_sha256"], "source_native_attempt_id": source_request["attempt_id"], "native_receipt": native_ref, "typed_request": str(typed_request_path), "xmf_request": str(xmf_request_path), "render_request": str(render_request_path), "typed_actual_sha256": None, "xmf_actual_sha256": None, "render_actual_sha256": None, "actual_typed_frames": None, "actual_rendered_frames": None})

    dump(PACKAGE / "render" / "camera-spec.json", {"schema": "ds02.f4.root242-camera-spec-index.v1", "family_id": "F4", "camera_strategy": "Root023 full-state native valid-point scan", "cases": camera_map})
    dump(PACKAGE / "render" / "contact-page-keys.json", contact_pages())
    dump(PACKAGE / "render" / "n3-vector-spec.json", {"schema": "ds02.f4.root023-n3-vector-spec.v1", "field": "velocity", "attribute_type": "Vector", "semantic_type": "N3", "components": ["vx", "vy", "vz"], "coordinate_frame": "DualSPHysics Cartesian (x,y,z)", "preserve_all_native_fields": True})
    dump(PACKAGE / "evidence" / "root242-native-receipts.json", {"schema": "ds02.f4.root242-native-receipt-evidence.v1", "claim_boundary": "Root242 native completed/0 receipts and enabled request identities only; no typed frames, H5, XMF, or visual completeness claim.", "arrays_read_by_source": False, "jobs_started_by_source": False, "cases": native_rows})
    dump(PACKAGE / "source-binding.json", {"schema": "ds02.f4.root242-typed-xmf-render-source-binding.v1", "scope_id": SCOPE, "family_id": "F4", "claim_boundary": "Six existing Root242 native attempts are bound by actual JSON receipts. Typed conversion, XMF export, and Root023 full-state rendering remain disabled and future SHA values are null until Root independently runs and audits each stage.", "native_case_count": len(case_records), "independent_case_count_increment": 0, "arrays_read_by_source": False, "jobs_started_by_source": False, "root230_policy": {"entry": ref(ROOT230_ENTRY), "home_policy": ref(ROOT230_HOME), "gpu_policy": ref(ROOT134_GPU), "contract": ref(ROOT230_CONTRACT), "home_free_gib_floor": 500, "nvme_free_gib_floor": 100, "nvme_peak_gib": 24, "solver_concurrency_cap": 8}, "resource_window": ref(RESOURCE_WINDOW), "cases": case_records, "requests": all_requests})
    dump(PACKAGE / "requests" / "index.json", {"schema": "ds02.f4.root242-typed-xmf-render-request-index.v1", "scope_id": SCOPE, "family_id": "F4", "launch_allowed": False, "independent_case_count_increment": 0, "requests": all_requests})
    print(json.dumps({"package": str(PACKAGE), "case_count": len(case_records), "request_count": len(all_requests), "arrays_read_by_source": False}, indent=2))


if __name__ == "__main__":
    main()
