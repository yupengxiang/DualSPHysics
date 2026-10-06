#!/usr/bin/env python3
"""Compare Root920 success and Root934 failure using JSON metadata only.

The comparison deliberately opens only JSON files and never opens, hashes, or
copies H5/BI4/CSV/DAT/VTK scientific payloads. It records interface differences
for Root142's separate no-H5 diagnostic; it does not identify a renderer root
cause.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    """lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003"""
)
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F3_PACKAGE = Path(__file__).resolve().parents[1]

ROOT920 = BASE / "root_stage1_F6_actual722_full241_independent_Renderer023_CPU24_16GiB_Home_admission_920"
ROOT934 = BASE / "root_stage1_NVMe3GiB_fullnative_renderer_first1_then_shared2_F6remaining23_F2ready3_F5ready1_934"
ROOT937 = DATA / "families/F6/F6_METADATA_PARAVIEW_IMPORT_DIAGNOSTIC/root-stage1-registered-pv-nested-import-only-no-H5-root937"


def read_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() != ".json":
        raise ValueError(f"metadata comparison accepts JSON only: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"metadata JSON must be an object: {path}")
    return value


def manifest_ref(path_value: Any) -> dict[str, Any]:
    if not isinstance(path_value, str):
        return {"path": path_value, "exists": False, "opened": False}
    path = Path(path_value)
    result: dict[str, Any] = {"path": str(path), "exists": path.is_file(), "opened": False}
    # Manifest JSON is metadata. Its XMF is intentionally only retained as a
    # reference; this function never opens the XMF or any DataItem target.
    if path.suffix.lower() == ".json" and path.is_file():
        manifest = read_json(path)
        result.update({
            "opened": True,
            "schema": manifest.get("schema"),
            "frames": manifest.get("frames"),
            "particles": manifest.get("particles"),
            "xdmf_ref": manifest.get("xdmf"),
            "xdmf_opened": False,
        })
    return result


def env_view(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"value_type": type(value).__name__}
    return {str(key): str(value[key]) for key in sorted(value)}


def main() -> dict[str, Any]:
    req920 = read_json(ROOT920 / "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0375_YAWM12_DP025-render-request.json")
    rec920 = read_json(DATA / "families/F6/F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0375_YAWM12_DP025/"
                       "root-stage1-f6-f6-stage1-angular-release-dxyz-s0375-yawm12-dp025-full241-native023-render-103-independent-own-family-successor-root920/execution-receipt.json")
    report920 = read_json(DATA / "families/F6/F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0375_YAWM12_DP025/"
                          "root-stage1-f6-f6-stage1-angular-release-dxyz-s0375-yawm12-dp025-full241-native023-render-103-independent-own-family-successor-root920/render/paraview-full-animation-report.json")
    req934 = read_json(ROOT934 / "requests/F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0625_YAWM06_DP025-render-request.json")
    wrap934 = read_json(ROOT934 / "wrapper-requests/F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0625_YAWM06_DP025-enabled-wrapper.json")
    rec934 = read_json(DATA / "families/F6/F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0625_YAWM06_DP025/"
                       "root-stage1-f6-f6_stage1_angular_release_dxyz_s0625_yawm06_dp025-full241-NVMe3GiB-root934/execution-receipt.json")
    controller934 = read_json(ROOT934 / "controller-result.json")
    audit113 = read_json(F3_PACKAGE.parent / "root_followup_113_f3_root934_metadata_binding_audit_v1/metadata/root934-audit-report.json")
    diagnostic937 = read_json(ROOT937 / "import-diagnostic.json")

    env920 = env_view(req920.get("render_environment"))
    env934 = env_view(wrap934.get("render_environment"))
    # Root920 records the direct Root023 invocation in the execution receipt.
    # Root934 records the outer registered entry in its receipt and the inner
    # Root023 argv template in the wrapper request.
    command920 = rec920.get("command")
    command934 = rec934.get("command")
    inner934 = wrap934.get("renderer_argv_template")
    result = {
        "schema": "ds02.stage1.f3.fresh114.root920-root934-metadata-comparison.v1",
        "source_only": True,
        "science_payloads_opened_or_hashed": False,
        "payload_boundary": {
            "opened": [
                "JSON request/receipt/controller/report/diagnostic metadata",
                "JSON manifest metadata only",
            ],
            "not_opened": ["H5", "BI4", "CSV", "DAT", "VTK", "XMF DataItem targets"],
        },
        "root920_success": {
            "case_id": req920.get("case_id"),
            "status": rec920.get("status"),
            "returncode": rec920.get("returncode"),
            "output_bytes": rec920.get("bytes"),
            "frames": report920.get("frames"),
            "source_frames": report920.get("source_frames"),
            "all_frames_rendered": report920.get("all_frames_rendered"),
            "actual_times_preserved_exactly": report920.get("actual_times_preserved_exactly"),
            "pvpython": req920.get("command", [None])[-7] if isinstance(req920.get("command"), list) and len(req920.get("command")) >= 7 else None,
            "argv": command920,
            "render_environment": env920,
            "manifest_ref": manifest_ref(req920.get("xmf_manifest") or req920.get("manifest")),
            "output_root": rec920.get("output_root"),
            "renderer_worker_ref": req920.get("worker"),
            "renderer_worker_sha256": req920.get("worker_sha256"),
            "runner_source": rec920.get("runner_source"),
        },
        "root934_failure": {
            "case_id": req934.get("case_id"),
            "status": rec934.get("status"),
            "returncode": rec934.get("returncode"),
            "output_bytes": rec934.get("bytes"),
            "elapsed_seconds": rec934.get("elapsed_seconds"),
            "controller_result": {
                "requested": controller934.get("requested"),
                "actual_fullnative_completed0": controller934.get("actual_fullnative_completed0"),
                "pending_held": controller934.get("pending_held"),
                "case_credit": controller934.get("case_credit"),
            },
            "outer_argv": command934,
            "inner_root023_argv_template": inner934,
            "render_environment": env934,
            "manifest_ref": manifest_ref(wrap934.get("manifest")),
            "output_root": rec934.get("output_root"),
            "renderer_worker_ref": wrap934.get("renderer"),
            "renderer_worker_sha256": wrap934.get("renderer_sha256"),
            "registered_entry_ref": command934[1] if isinstance(command934, list) and len(command934) > 1 else None,
            "rejection_evidence_from_fresh113": {
                "status": audit113["controller_failure_evidence"].get("rejection_status"),
                "stage_removed": audit113["controller_failure_evidence"].get("rejection_stage_removed"),
                "stderr_tail_present": audit113["controller_failure_evidence"].get("rejection_stderr_tail_present"),
                "argv_present": audit113["controller_failure_evidence"].get("rejection_actual_argv_present"),
                "root_cause_known": audit113["controller_failure_evidence"].get("root_cause_known", False),
            },
        },
        "pv_environment_comparison": {
            "exact_equal": env920 == env934,
            "root920": env920,
            "root934": env934,
            "difference": "none in registered render_environment values" if env920 == env934 else "values differ; see maps",
        },
        "renderer_source_comparison": {
            "root920_worker_sha256": req920.get("worker_sha256"),
            "root934_wrapper_renderer_sha256": wrap934.get("renderer_sha256"),
            "same_renderer_sha256": req920.get("worker_sha256") == wrap934.get("renderer_sha256"),
            "note": "The failure used the same Root023 renderer source digest, behind a different registered wrapper path.",
        },
        "argv_and_wrapper_comparison": {
            "direct_success_path": "Root920 receipt contains direct pvpython -> Root023 renderer argv",
            "failure_path": "Root934 receipt contains venv python -> registered_render_entry -> fresh112 worker; wrapper holds the Root023 argv template",
            "direct_vs_outer_argv_equal": command920 == command934,
            "root023_template_present_in_failure_wrapper": isinstance(inner934, list),
            "no_root_cause_inferred": True,
        },
        "manifest_comparison": {
            "same_schema_and_shape": (
                result_manifest := manifest_ref(req920.get("xmf_manifest") or req920.get("manifest")),
                manifest_ref(wrap934.get("manifest")),
            ),
            "note": "Both metadata manifests reference 241 frames and 417505 particles; their XMF and DataItem payloads were not opened.",
        },
        "root937_no_h5_import_diagnostic": {
            "status": diagnostic937.get("status"),
            "returncode": diagnostic937.get("returncode"),
            "science_payload_IO": diagnostic937.get("science_payload_IO"),
            "stderr_empty": diagnostic937.get("stderr_tail") == "",
            "pvpython_argv": diagnostic937.get("expanded_argv"),
            "imports_passed": diagnostic937.get("status") == "imports_pass",
            "imports_tested_by_probe": [
                "numpy", "PIL.Image", "PIL.ImageDraw", "paraview.servermanager",
                "paraview.simple", "vtkmodules.util.numpy_support",
            ],
            "renderer_specific_helper_not_tested": "paraview.vtk.util.numpy_support",
            "scope_limitation": "imports-only probe; it did not call Root023 load_manifest/render_case and did not read H5",
        },
        "interpretation": "Root934 failure remains unexplained by this metadata comparison; Root142 must use the registered no-H5 diagnostic and preserve the original failure receipt.",
    }
    # The tuple above is convenient while constructing the comparison but JSON
    # must contain an object with named sides.
    left, right = result["manifest_comparison"]["same_schema_and_shape"]
    result["manifest_comparison"]["same_schema_and_shape"] = {
        "root920": left,
        "root934": right,
        "schema_equal": left.get("schema") == right.get("schema"),
        "frames_equal": left.get("frames") == right.get("frames"),
        "particles_equal": left.get("particles") == right.get("particles"),
    }
    return result


if __name__ == "__main__":
    output = main()
    print(json.dumps(output, indent=2, sort_keys=True))
