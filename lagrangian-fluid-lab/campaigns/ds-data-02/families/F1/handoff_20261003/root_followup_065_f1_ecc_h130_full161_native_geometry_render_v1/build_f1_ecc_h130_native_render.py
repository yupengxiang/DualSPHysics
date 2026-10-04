#!/usr/bin/env python3
"""Build the disabled F1 H130 full-native geometry render handoff.

This builder is metadata-only.  ``--mode plan`` validates the already recorded
native/typed receipts and writes a source fixture with a null XMF digest.  A
root-owned ``--mode bind`` run may be used after Root121 has completed; it
reads only JSON/XML metadata, hashes the completed XMF, and writes another
disabled request.  It never opens the trajectory HDF5 and never launches
ParaView or any other worker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable


PACKAGE = Path(__file__).resolve().parent
FAMILY_DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
CASE_DATA = FAMILY_DATA / "F1_STAGE1_ECC_H130_DP010"
ROOT121 = CASE_DATA / "root-stage1-f1-ecc130-full161-normal-dynamic-121"
ROOT121_MANIFEST = ROOT121 / "manifest.json"
ROOT121_RECEIPT = ROOT121 / "execution-receipt.json"
ROOT121_XMF = ROOT121 / "case.xmf"
TRAJECTORY_H5 = CASE_DATA / "root-stage1-f1-ecc-h130-full161-native-typed-nvme-063" / "trajectory.h5"
NATIVE_RECEIPT = CASE_DATA / "root-stage1-f1-ecc-h130-full161-native-visual-production-094" / "execution-receipt.json"
TYPED_RECEIPT = CASE_DATA / "root-stage1-f1-ecc-h130-full161-native-typed-nvme-063" / "execution-receipt.json"
CONVERSION_REPORT = CASE_DATA / "root-stage1-f1-ecc-h130-full161-native-typed-nvme-063" / "conversion-report.json"
OWNER = PACKAGE / "owners" / "F1_STAGE1_ECC_H130_DP010.owner.json"

INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
LAB = INTEGRATION / "lagrangian-fluid-lab"
RENDERER = LAB / "campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py"
STRICT_DISPATCH = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
GOAL = LAB / "campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
PVPYTHON = Path("/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython")
ENV = Path("/usr/bin/env")
EGL_VENDOR = Path("/usr/share/glvnd/egl_vendor.d/50_mesa.json")

CASE_ID = "F1_STAGE1_ECC_H130_DP010"
PHYSICAL_CASE_ID = "F1_ECC_HEAD_130_UNCHANGED_MOTHER_GEOMETRY_V1"
PHYSICAL_CONDITION_SHA256 = "16ba07faf7b61f7d97f4bfc9d88a315293292107f1390ca860c15825a3bdb36e"
RENDERER_SHA256 = "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66"
EXPECTED_FRAMES = 161
EXPECTED_PARTICLES = 136276
EXPECTED_FLUID_PARTICLES = 34840
WINDOW_S = [0.0, 1.6]
SAVE_INTERVAL_S = 0.01
DP_M = 0.01


class BindingError(RuntimeError):
    """Raised when a recorded source contract cannot be bound safely."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BindingError(f"missing metadata file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BindingError(f"invalid JSON metadata: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BindingError(f"metadata root must be an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    if path.suffix.lower() in {".h5", ".hdf5", ".hdf", ".npy", ".npz"}:
        raise BindingError(f"array-bearing file may not be opened by this builder: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except FileNotFoundError as exc:
        raise BindingError(f"missing source file: {path}") from exc
    return digest.hexdigest()


def ref(path: Path, *, digest: str | None = None, read_policy: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(path), "sha256": digest if digest is not None else sha256_file(path)}
    if read_policy is not None:
        item["read_policy"] = read_policy
    return item


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BindingError(message)


def require_completed(receipt: dict[str, Any], path: Path, label: str) -> None:
    require(receipt.get("status") == "completed", f"{label} is not completed: {path}")
    require(receipt.get("returncode") == 0, f"{label} returncode is not zero: {path}")


def contact_pages(frame_count: int = EXPECTED_FRAMES, page_size: int = 24) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for page, start in enumerate(range(0, frame_count, page_size)):
        end = min(frame_count, start + page_size)
        pages.append(
            {
                "key": f"all_frames_{page:03d}",
                "filename": f"all_frames_{page:03d}.png",
                "frame_start": start,
                "frame_end_exclusive": end,
                "frame_count": end - start,
            }
        )
    return pages


def validate_renderer() -> dict[str, Any]:
    require(RENDERER.exists(), f"mature renderer is missing: {RENDERER}")
    actual = sha256_file(RENDERER)
    require(actual == RENDERER_SHA256, f"mature renderer hash changed: {actual}")
    source = RENDERER.read_text(encoding="utf-8")
    markers = {
        "auto_all_frame_nativebounds": "_scan_native_bounds(reader, scan_times" in source,
        "actual_fixed_cutaway": "_display_cutaway" in source and '"filter": "display-only Clip plane"' in source,
        "native_unclipped_source": '"source_reader_unclipped": True' in source,
        "full_unclipped_proxies": '"full_unclipped_proxies_retained_in_pvsm": True' in source,
        "all_frames_contract": '"all_frames_rendered"' in source,
        "contact_sheet_contract": "contact_sheet_paths.append" in source,
    }
    require(all(markers.values()), f"mature renderer contract markers are incomplete: {markers}")
    return {
        "path": str(RENDERER),
        "sha256": actual,
        "revision": "f2-root-followup-053-stage1-visual-renderer-v2",
        "contract_markers": markers,
    }


def validate_source_metadata() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    owner = read_json(OWNER)
    native = read_json(NATIVE_RECEIPT)
    typed = read_json(TYPED_RECEIPT)
    conversion = read_json(CONVERSION_REPORT)
    root_manifest = read_json(ROOT121_MANIFEST)

    require(owner.get("family_id") == "F1", "owner family mismatch")
    require(owner.get("case_id") == CASE_ID, "owner case mismatch")
    require(owner.get("physical_case_id") == PHYSICAL_CASE_ID, "owner physical case mismatch")
    require(owner.get("physical_condition_sha256") == PHYSICAL_CONDITION_SHA256, "owner physical condition mismatch")
    require(owner.get("native_typed_identity", {}).get("actual_3d") is True, "owner is not marked actual 3D")
    require(owner.get("native_typed_identity", {}).get("actual_total_particles") == EXPECTED_PARTICLES, "owner total count mismatch")
    require(owner.get("native_typed_identity", {}).get("actual_fluid_particles") == EXPECTED_FLUID_PARTICLES, "owner fluid count mismatch")
    require(owner.get("native_frame_contract", {}).get("expected_saved_frames") == EXPECTED_FRAMES, "owner frame count mismatch")
    require(owner.get("native_frame_contract", {}).get("dp_m") == DP_M, "owner dp mismatch")
    require(owner.get("native_frame_contract", {}).get("save_interval_s") == SAVE_INTERVAL_S, "owner save interval mismatch")
    require(owner.get("mass_audit_observation", {}).get("mass_rescaling") is False, "mass rescaling is not frozen false")
    require(owner.get("claims", {}).get("independent_case_count_increment") == 0, "owner count increment is not zero")

    require_completed(native, NATIVE_RECEIPT, "Root094 native receipt")
    require_completed(typed, TYPED_RECEIPT, "typed063 receipt")
    require(conversion.get("frames") == EXPECTED_FRAMES, "typed conversion frame count mismatch")
    require(conversion.get("particles") == EXPECTED_PARTICLES, "typed conversion particle count mismatch")

    require(root_manifest.get("schema") == "ds02.stage1.paraview-temporal-product.v1", "Root121 manifest schema mismatch")
    require(root_manifest.get("family_id") == "F1", "Root121 family mismatch")
    require(root_manifest.get("case_id") == CASE_ID, "Root121 case mismatch")
    require(root_manifest.get("physical_case_id") == PHYSICAL_CASE_ID, "Root121 physical case mismatch")
    require(root_manifest.get("physical_condition_sha256") == PHYSICAL_CONDITION_SHA256, "Root121 condition mismatch")
    require(root_manifest.get("expected_frames") == EXPECTED_FRAMES, "Root121 expected frame count mismatch")
    require(root_manifest.get("expected_particles") == EXPECTED_PARTICLES, "Root121 expected particle count mismatch")
    require(root_manifest.get("physical_window_s") == WINDOW_S, "Root121 physical window mismatch")
    require(root_manifest.get("save_interval_s") == SAVE_INTERVAL_S, "Root121 save interval mismatch")
    require(root_manifest.get("source_h5_read_only") is True, "Root121 H5 policy is not read-only")
    require(root_manifest.get("independent_case_count_increment") == 0, "Root121 count increment is not zero")
    require(root_manifest.get("trajectory_h5") == str(TRAJECTORY_H5), "Root121 trajectory path mismatch")
    require(root_manifest.get("xdmf") == str(ROOT121_XMF), "Root121 XMF path mismatch")
    require(root_manifest.get("source_h5_sha256"), "Root121 recorded H5 digest is missing")
    require(TRAJECTORY_H5.exists(), f"recorded trajectory path is missing: {TRAJECTORY_H5}")

    # Keep the H5 digest as recorded provenance.  The suffix guard in
    # sha256_file ensures this builder can never open the trajectory.
    renderer = validate_renderer()
    return owner, native, typed, conversion, root_manifest | {"_renderer": renderer}


def stable_inputs(root_manifest: dict[str, Any], *, bind: bool) -> tuple[list[Path], dict[str, str | None]]:
    # XMF, its temporal manifest, and the H5 are deliberately represented as
    # future/current bindings.  In plan mode their digests remain null even if
    # a Root process happens to finish between two source-only invocations.
    paths = [
        PVPYTHON,
        ENV,
        EGL_VENDOR,
        RENDERER,
        STRICT_DISPATCH,
        RUNTIME,
        GOAL,
        OWNER,
        NATIVE_RECEIPT,
        TYPED_RECEIPT,
        CONVERSION_REPORT,
        ROOT121_RECEIPT,
        ROOT121_MANIFEST,
        ROOT121_XMF,
        TRAJECTORY_H5,
    ]
    hashes: dict[str, str | None] = {}
    for path in paths:
        key = str(path)
        if path in {ROOT121_MANIFEST, ROOT121_XMF} and not bind:
            hashes[key] = None
        elif path == TRAJECTORY_H5:
            recorded = root_manifest.get("source_h5_sha256")
            require(isinstance(recorded, str) and len(recorded) == 64, "recorded H5 digest is invalid")
            hashes[key] = recorded
        else:
            hashes[key] = sha256_file(path)
    return paths, hashes


def binding_document(root_manifest: dict[str, Any], *, bind: bool, xmf_digest: str | None) -> dict[str, Any]:
    renderer = root_manifest["_renderer"]
    pages = contact_pages()
    manifest_digest = sha256_file(ROOT121_MANIFEST) if bind else None
    receipt_digest = sha256_file(ROOT121_RECEIPT)
    owner_digest = sha256_file(OWNER)
    native_digest = sha256_file(NATIVE_RECEIPT)
    typed_digest = sha256_file(TYPED_RECEIPT)
    conversion_digest = sha256_file(CONVERSION_REPORT)
    document: dict[str, Any] = {
        "schema": "ds02.f1.stage1.native-geometry-render-binding.v1",
        "family_id": "F1",
        "case_id": CASE_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "physical_condition_sha256": PHYSICAL_CONDITION_SHA256,
        "source_only": True,
        "independent_case_count_increment": 0,
        "precision_status": "not_accepted",
        "visual_status": "pending root inspection of full161 native geometry render",
        "physical_binding": {
            "head_height_m": 0.13,
            "dp_m": DP_M,
            "physical_window_s": WINDOW_S,
            "save_interval_s": SAVE_INTERVAL_S,
            "expected_frames": EXPECTED_FRAMES,
            "expected_particles": EXPECTED_PARTICLES,
            "expected_fluid_particles": EXPECTED_FLUID_PARTICLES,
            "native_3d": True,
            "geometry_source": "Root094 native output; unchanged mother geometry",
            "native_particle_identity_preserved": True,
            "camera_or_source_crop": False,
        },
        "source_provenance": {
            "canonical_owner": ref(OWNER, digest=owner_digest),
            "native094_receipt": ref(NATIVE_RECEIPT, digest=native_digest),
            "typed063_receipt": ref(TYPED_RECEIPT, digest=typed_digest),
            "typed063_conversion_report": ref(CONVERSION_REPORT, digest=conversion_digest),
            "root121_execution_receipt": ref(ROOT121_RECEIPT, digest=receipt_digest),
            "root121_temporal_manifest": {
                "path": str(ROOT121_MANIFEST),
                "sha256": manifest_digest,
                "status": "completed_metadata_bound" if bind else "pending_root121_completion",
            },
            "trajectory_h5": {
                "path": str(TRAJECTORY_H5),
                "sha256": root_manifest.get("source_h5_sha256"),
                "read_policy": "recorded provenance only; this builder never opens H5",
            },
        },
        "temporal_source": {
            "manifest_path": str(ROOT121_MANIFEST),
            "xdmf_path": str(ROOT121_XMF),
            "xdmf_sha256": xmf_digest,
            "xdmf_status": "completed_and_hashed" if bind else "pending_root121_completion",
            "frames": EXPECTED_FRAMES,
            "particles": EXPECTED_PARTICLES,
            "actual_saved_time_axis_preserved": True,
        },
        "renderer": {
            **renderer,
            "mode": "full161_native_geometry",
            "camera_policy": "auto-all-frame-nativebounds",
            "camera_bounds_override": None,
            "domain_bounds_override": None,
            "cutaway_policy": "actualfixedcutaway",
            "fixed_cutaway": {
                "filter": "display-only Clip plane",
                "plane_normal": [0.0, 1.0, 0.0],
                "source_reader_unclipped": True,
                "full_unclipped_proxies_retained_in_pvsm": True,
            },
            "native_type_aliases": {
                "boundary": [0],
                "fluid": [3],
                "moving": [1],
                "floating": [2],
            },
        },
        "contact_sheet_contract": {
            "full_animation": True,
            "diagnostic_frames": None,
            "page_size": 24,
            "page_count": len(pages),
            "page_keys": [page["key"] for page in pages],
            "pages": pages,
            "gif_key": "full_saved_animation.gif",
            "pvsm_key": "case.pvsm",
            "report_key": "paraview-full-animation-report.json",
        },
        "output_contract": {
            "frames_directory": "frames/",
            "contact_sheets": [page["filename"] for page in pages],
            "full_saved_animation": "full_saved_animation.gif",
            "state": "case.pvsm",
            "report": "paraview-full-animation-report.json",
        },
        "mass_policy": "native_massfluid_no_rescaling",
        "no_numeric_array_read_by_builder": True,
        "no_job_launch_by_builder": True,
        "request_status": "disabled_pending_root_authorization_and_visual_review",
    }
    return document


def render_request(root_manifest: dict[str, Any], binding: dict[str, Any], *, bind: bool) -> dict[str, Any]:
    paths, hashes = stable_inputs(root_manifest, bind=bind)
    page_keys = binding["contact_sheet_contract"]["page_keys"]
    command = [
        "/usr/bin/env",
        "VTK_SMP_MAX_THREADS=2",
        "LP_NUM_THREADS=2",
        "LIBGL_ALWAYS_SOFTWARE=1",
        "MESA_LOADER_DRIVER_OVERRIDE=llvmpipe",
        "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json",
        "VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow",
        "QT_QPA_PLATFORM=offscreen",
        "OMP_NUM_THREADS=2",
        str(PVPYTHON),
        "--force-offscreen-rendering",
        str(RENDERER),
        "--manifest",
        str(ROOT121_MANIFEST),
        "--output-dir",
        "{attempt_root}",
    ]
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F1",
        "case_id": CASE_ID,
        "attempt_id": "root-stage1-f1-ecc130-full161-native-geometry-render-065",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 14400,
        "estimated_storage_bytes": 8589934592,
        "cwd": str(LAB),
        "worktree_root": str(INTEGRATION),
        "command": command,
        "input_files": [str(path) for path in paths],
        "input_sha256": hashes,
        "render_binding": {
            "path": str(PACKAGE / ("metadata/bound-h130-native-geometry-render-binding.json" if bind else "metadata/source-plan.json")),
            "xdmf_sha256": binding["temporal_source"]["xdmf_sha256"],
            "camera_policy": "auto-all-frame-nativebounds",
            "cutaway_policy": "actualfixedcutaway",
            "full_saved_frames": EXPECTED_FRAMES,
            "contact_page_keys": page_keys,
            "diagnostic_frames": None,
        },
        "launch_allowed": False,
        "launch_owner": "root",
        "disabled_reason": "Source-only handoff. Root must authorize the disabled request after checking the completed Root121 metadata and the visual review scope.",
        "source_only": True,
        "independent_case_count_increment": 0,
        "production_approval": "none from source-only disabled request",
        "claim": "A derived full161 native-geometry render request for one existing H130 physical condition; it makes no precision, count, or visual acceptance claim.",
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(mode: str) -> dict[str, Any]:
    owner, native, typed, conversion, root_manifest = validate_source_metadata()
    renderer = root_manifest.pop("_renderer")
    root_manifest["_renderer"] = renderer
    bind = mode == "bind"
    xmf_digest: str | None = None
    if bind:
        root_receipt = read_json(ROOT121_RECEIPT)
        require_completed(root_receipt, ROOT121_RECEIPT, "Root121 dynamic receipt")
        require(ROOT121_XMF.exists(), f"Root121 XMF is missing: {ROOT121_XMF}")
        xmf_digest = sha256_file(ROOT121_XMF)
        recorded = root_manifest.get("xdmf_sha256")
        require(recorded == xmf_digest, f"Root121 XMF digest mismatch: recorded={recorded} actual={xmf_digest}")

    binding = binding_document(root_manifest, bind=bind, xmf_digest=xmf_digest)
    validation = {
        "schema": "ds02.f1.stage1.native-geometry-render-source-validation.v1",
        "mode": mode,
        "case_id": CASE_ID,
        "checks": {
            "owner_actual_3d_and_counts": True,
            "native094_completed_zero": True,
            "typed063_completed_zero": True,
            "root121_json_contract": True,
            "renderer_sha256_and_contract": True,
            "trajectory_h5_opened": False,
            "numeric_arrays_read": False,
            "job_launched": False,
        },
        "renderer_sha256": renderer["sha256"],
        "physical_condition_sha256": PHYSICAL_CONDITION_SHA256,
        "xdmf_sha256": xmf_digest,
    }
    if bind:
        write_json(PACKAGE / "metadata/bound-h130-native-geometry-render-binding.json", binding)
        write_json(PACKAGE / "requests/F1_STAGE1_ECC_H130_DP010.full161-native-geometry-render.disabled.json", render_request(root_manifest, binding, bind=True))
        write_json(PACKAGE / "metadata/bind-validation.json", validation)
    else:
        write_json(PACKAGE / "metadata/source-plan.json", binding)
        write_json(PACKAGE / "requests/F1_STAGE1_ECC_H130_DP010.full161-native-geometry-render.pending.disabled.json", render_request(root_manifest, binding, bind=False))
        write_json(PACKAGE / "metadata/source-validation.json", validation)
    return {
        "mode": mode,
        "package": str(PACKAGE),
        "xdmf_sha256": xmf_digest,
        "contact_page_count": len(binding["contact_sheet_contract"]["pages"]),
        "launch_allowed": False,
        "trajectory_h5_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("plan", "bind"), default="plan")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.mode), indent=2, sort_keys=True))
    except BindingError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
