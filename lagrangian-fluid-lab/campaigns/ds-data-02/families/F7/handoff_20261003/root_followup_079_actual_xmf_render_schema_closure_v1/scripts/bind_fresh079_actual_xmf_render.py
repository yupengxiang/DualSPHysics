#!/usr/bin/env python3
"""Bind completed F7 XMF metadata to disabled Root023 render requests.

This adapter is deliberately metadata-only.  It reads Root411 XMF requests,
execution receipts, manifests, and XDMF XML metadata.  It validates the
producer scope, 601-frame/70179-particle 3-D contract, and the XDMF vector
shape contract (N 3, with the particle axis retained).  It never opens,
hashes, or copies BI4, H5, CSV, DAT, or other scientific payloads, and never
starts XMF, ParaView, or a solver.

The output directory is a staging directory for disabled Root023 requests.
Run it only after the registered Root411 XMF attempts have completed/0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable


CASES = [
    f"F7_OBSTACLE_QUINTIC_B08_A{number:03d}P5"
    for number in (30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42,
                   43, 44, 45, 46, 47, 48, 49, 50, 54, 59, 64)
]
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
RAW_SUFFIXES = {".bi4", ".ibi4", ".csv", ".h5", ".hdf5", ".dat", ".vtk", ".npy", ".npz"}
SCOPE_SCHEMA = "ds-data-02.physical-binding.v1"
CONVERSION_SCHEMA = "ds-data-02.bi4-direct-conversion.v1"
XMF_MANIFEST_SCHEMA = "ds02.stage1.paraview-temporal-product.v1"
RENDERER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py"
)
ROOT142_LAUNCH = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_home_floor_inventory_dispatch_142/launch.py"
)
ROOT142_POLICY = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py"
)
RESOURCE_APPROVAL = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
)
PYTHON = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/"
    "DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
)


class AdapterError(ValueError):
    """Raised for a metadata contract violation."""


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AdapterError(f"JSON root is not an object: {path}")
    return value


def dump_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise AdapterError(f"{label} does not exist: {path}")
    return path


def sha256_metadata(path: Path) -> str:
    path = path.resolve()
    if path.suffix.lower() in RAW_SUFFIXES:
        raise AdapterError(f"scientific payload hashing is forbidden: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise AdapterError(f"{label} must be a 64-character hexadecimal digest")
    return value.lower()


def unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def expected_counts(value: Any) -> None:
    if not isinstance(value, dict):
        raise AdapterError("expected_counts must be an object")
    expected = {"total": 70179, "fixed": 27495, "moving": 1984,
                "floating": 0, "fluid": 40700, "dimension": 3}
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            raise AdapterError(f"expected_counts[{key}] is {value.get(key)!r}, wanted {wanted}")


def request_for(root411: Path, case_id: str) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    request_path = root411 / f"{case_id}-xmf-request.json"
    binding_path = root411 / f"{case_id}-actual-xmf-binding.json"
    request = load_json(require_file(request_path, "Root411 XMF request"))
    binding = load_json(require_file(binding_path, "Root411 XMF binding"))
    if request.get("case_id") != case_id or binding.get("case_id") != case_id:
        raise AdapterError(f"case mismatch in Root411 metadata for {case_id}")
    if request.get("family_id") != "F7" or binding.get("family_id") != "F7":
        raise AdapterError(f"family mismatch in Root411 metadata for {case_id}")
    if request.get("producer_scope_schema") != SCOPE_SCHEMA:
        raise AdapterError(f"Root411 producer_scope_schema missing for {case_id}")
    q = require_hex(request.get("producer_physical_condition_sha256"), f"{case_id} producer scope")
    if q != require_hex(request.get("canonical_physical_binding_sha256"), f"{case_id} canonical scope"):
        raise AdapterError(f"Root411 canonical/producer scope mismatch for {case_id}")
    source_plan = require_hex(request.get("source_plan_condition_sha256"), f"{case_id} source plan")
    if source_plan == q:
        raise AdapterError(f"Root411 conflates source-plan and producer scope for {case_id}")
    if binding.get("producer_physical_condition_sha256") != q:
        raise AdapterError(f"Root411 binding producer scope mismatch for {case_id}")
    if binding.get("producer_scope_schema") != SCOPE_SCHEMA:
        raise AdapterError(f"Root411 binding producer_scope_schema missing for {case_id}")
    if request.get("expected_frames") != 601 or request.get("expected_native_frames") != 601:
        raise AdapterError(f"Root411 frame contract mismatch for {case_id}")
    if request.get("expected_particles") != 70179:
        raise AdapterError(f"Root411 particle contract mismatch for {case_id}")
    expected_counts(request.get("expected_counts"))
    if request.get("output_directory_contract") != "{attempt_root}/xdmf":
        raise AdapterError(f"Root411 XMF output directory contract changed for {case_id}")
    if request.get("future_outputs", {}).get("manifest") != "{attempt_root}/xdmf/manifest.json":
        raise AdapterError(f"Root411 manifest output contract changed for {case_id}")
    return request_path, request, binding_path, binding


def check_receipt(path: Path, case_id: str) -> str:
    receipt = load_json(require_file(path, f"XMF execution receipt for {case_id}"))
    if (receipt.get("status"), receipt.get("returncode")) != ("completed", 0):
        raise AdapterError(f"XMF is not completed/0 for {case_id}: {path}")
    request = receipt.get("request")
    if isinstance(request, dict) and request.get("case_id") not in (None, case_id):
        raise AdapterError(f"XMF receipt case mismatch for {case_id}: {path}")
    return sha256_metadata(path)


def field_shape(manifest: dict[str, Any], name: str) -> list[int]:
    fields = manifest.get("fields")
    if not isinstance(fields, dict) or not isinstance(fields.get(name), dict):
        raise AdapterError(f"manifest field metadata missing: {name}")
    shape = fields[name].get("shape")
    if not isinstance(shape, list) or not all(isinstance(x, int) for x in shape):
        raise AdapterError(f"manifest field shape is invalid: {name}")
    return shape


def check_manifest(manifest_path: Path, xmf_path: Path, case_id: str, q: str) -> dict[str, Any]:
    manifest = load_json(require_file(manifest_path, f"XMF manifest for {case_id}"))
    if manifest.get("schema") != XMF_MANIFEST_SCHEMA:
        raise AdapterError(f"manifest schema mismatch for {case_id}")
    if manifest.get("family_id") != "F7" or manifest.get("physical_case_id") != case_id:
        raise AdapterError(f"manifest physical identity mismatch for {case_id}")
    if manifest.get("producer_scope_schema") != SCOPE_SCHEMA:
        raise AdapterError(f"manifest producer scope schema missing for {case_id}")
    for key in ("physical_condition_sha256", "producer_physical_condition_sha256"):
        if require_hex(manifest.get(key), f"manifest {key}") != q:
            raise AdapterError(f"manifest {key} does not match Root411 actual scope for {case_id}")
    if manifest.get("frames") != 601 or manifest.get("particles") != 70179:
        raise AdapterError(f"manifest 601/70179 contract mismatch for {case_id}")
    times = manifest.get("actual_time_s")
    if not isinstance(times, list) or len(times) != 601:
        raise AdapterError(f"manifest time metadata does not contain 601 entries for {case_id}")
    required = {
        "position": [601, 70179, 3], "velocity": [601, 70179, 3],
        "valid": [601, 70179], "mass": [601, 70179],
        "density": [601, 70179], "pressure": [601, 70179], "type": [601, 70179],
        "initial_type": [70179], "particle_id": [70179],
        "particle_zone": [70179], "initial_mk": [70179], "initial_mass": [70179],
    }
    for name, shape in required.items():
        if field_shape(manifest, name) != shape:
            raise AdapterError(f"manifest shape mismatch for {case_id}/{name}")
    if manifest.get("source_h5_read_only") is not True:
        raise AdapterError(f"manifest did not mark H5 source read-only for {case_id}")
    declared_xmf = manifest.get("xdmf")
    if not isinstance(declared_xmf, str) or not declared_xmf:
        raise AdapterError(f"manifest XDMF path missing for {case_id}")
    resolved_xmf = Path(declared_xmf)
    if not resolved_xmf.is_absolute():
        resolved_xmf = (manifest_path.parent / resolved_xmf).resolve()
    if resolved_xmf != xmf_path.resolve():
        raise AdapterError(f"manifest XDMF path does not match receipt output for {case_id}")
    declared_sha = require_hex(manifest.get("xdmf_sha256"), f"manifest XDMF SHA for {case_id}")
    actual_sha = sha256_metadata(xmf_path)
    if actual_sha != declared_sha:
        raise AdapterError(f"manifest XDMF SHA is stale for {case_id}")
    return manifest


def check_xdmf(xmf_path: Path, case_id: str) -> dict[str, Any]:
    root = ET.parse(xmf_path).getroot()
    if root.tag.rsplit("}", 1)[-1] != "Xdmf":
        raise AdapterError(f"XDMF root is not Xdmf for {case_id}")
    collection = root.find("./Domain/Grid")
    if collection is None or collection.get("GridType") != "Collection":
        raise AdapterError(f"XDMF temporal collection missing for {case_id}")
    frames = collection.findall("./Grid")
    if len(frames) != 601:
        raise AdapterError(f"XDMF has {len(frames)} frames for {case_id}, wanted 601")
    names = {"valid", "initial_type", "particle_id", "particle_zone", "initial_mk",
             "initial_mass", "mass", "velocity", "density", "pressure", "type"}
    vector_dims = "70179 3"
    scalar_dims = "70179"
    for index, grid in enumerate(frames):
        topology = grid.find("Topology")
        if topology is None or topology.get("NumberOfElements") != "70179":
            raise AdapterError(f"XDMF topology mismatch at frame {index} for {case_id}")
        geometry = grid.find("Geometry/DataItem")
        if geometry is None or geometry.get("Dimensions") != vector_dims:
            raise AdapterError(f"XDMF geometry is not N 3 at frame {index} for {case_id}")
        attrs = {node.get("Name"): node for node in grid.findall("Attribute")}
        if set(attrs) != names:
            raise AdapterError(f"XDMF field set mismatch at frame {index} for {case_id}")
        velocity = attrs["velocity"].find("DataItem")
        if velocity is None or velocity.get("Dimensions") != vector_dims:
            raise AdapterError(f"XDMF velocity is not N 3 at frame {index} for {case_id}")
        for name, node in attrs.items():
            if name == "velocity":
                continue
            item = node.find("DataItem")
            if item is None or item.get("Dimensions") != scalar_dims:
                raise AdapterError(f"XDMF scalar {name} is not N at frame {index} for {case_id}")
    return {"frames": len(frames), "vector_dimensions": vector_dims,
            "scalar_dimensions": scalar_dims, "fields": sorted(names)}


def inherited_input_closure(request: dict[str, Any], additions: Iterable[Path]) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """Reuse Root411 attestations without opening raw payloads."""
    base_files = request.get("input_files")
    base_hashes = request.get("input_sha256")
    base_provenance = request.get("input_hash_provenance")
    if not isinstance(base_files, list) or not isinstance(base_hashes, dict):
        raise AdapterError("Root411 input closure is incomplete")
    files: list[str] = []
    hashes: dict[str, str] = {}
    provenance: dict[str, str] = {}
    stale_410 = "root_stage1_f7_actual24_typed376_fresh078_XMF_binding_410"
    for raw in base_files:
        path = str(raw)
        if stale_410 in path:
            continue
        if path not in base_hashes:
            raise AdapterError(f"Root411 input closure has no hash for {path}")
        value = base_hashes[path]
        if not isinstance(value, str) or not HEX64.fullmatch(value):
            raise AdapterError(f"Root411 input hash is not a digest for {path}")
        files.append(path)
        hashes[path] = value.lower()
        old = base_provenance.get(path) if isinstance(base_provenance, dict) else None
        if Path(path).suffix.lower() in RAW_SUFFIXES:
            provenance[path] = "inherited_root411_producer_attestation; adapter_did_not_read_or_hash_payload"
        else:
            provenance[path] = old if isinstance(old, str) else "inherited_root411_metadata_attestation"
    for path in additions:
        resolved = require_file(path, "render metadata input")
        key = str(resolved)
        if key in hashes:
            continue
        files.append(key)
        hashes[key] = sha256_metadata(resolved)
        provenance[key] = "adapter_hashed_bounded_JSON_XML_or_source"
    files = unique(files)
    if set(files) != set(hashes) or set(files) != set(provenance):
        raise AdapterError("render input_files/input_sha256/input_hash_provenance sets differ")
    return files, hashes, provenance


def render_command(manifest: Path) -> list[str]:
    return [
        "/usr/bin/env", "VTK_SMP_MAX_THREADS=2", "LP_NUM_THREADS=2",
        "LIBGL_ALWAYS_SOFTWARE=1", "MESA_LOADER_DRIVER_OVERRIDE=llvmpipe",
        "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json",
        "VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow", "QT_QPA_PLATFORM=offscreen",
        "OMP_NUM_THREADS=2", "/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython",
        "--force-offscreen-rendering", str(RENDERER), "--manifest", str(manifest),
        "--output-dir", "{attempt_root}/render",
    ]


def bind_case(root411: Path, data_root: Path, output: Path, case_id: str) -> dict[str, Any]:
    request_path, request, binding_path, binding = request_for(root411, case_id)
    attempt_id = request.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id.endswith("-normal-xmf-078"):
        raise AdapterError(f"unexpected Root411 XMF attempt for {case_id}: {attempt_id!r}")
    case_root = data_root / "families" / "F7" / case_id / attempt_id
    receipt_path = case_root / "execution-receipt.json"
    manifest_path = case_root / "xdmf" / "manifest.json"
    xmf_path = case_root / "xdmf" / "case.xmf"
    receipt_sha = check_receipt(receipt_path, case_id)
    manifest = check_manifest(manifest_path, xmf_path, case_id,
                              require_hex(request["producer_physical_condition_sha256"], "Root411 producer scope"))
    xdmf_shape = check_xdmf(xmf_path, case_id)
    q = require_hex(request["producer_physical_condition_sha256"], "Root411 producer scope")
    source_plan = require_hex(request["source_plan_condition_sha256"], "Root411 source plan")
    manifest_sha = sha256_metadata(manifest_path)
    xmf_sha = require_hex(manifest["xdmf_sha256"], "actual XDMF SHA")
    render_attempt = f"root-stage1-f7-{case_id.rsplit('_', 1)[1].lower()}-full601-native023-render-079"
    render_binding_path = output / "bindings" / f"{case_id}.full601-render-binding-079.actual-xmf-bound.json"
    render_request_path = output / "requests" / "render" / f"{case_id}.full601-native023-render-079.actual-xmf-bound.disabled-request.json"
    render_binding = {
        "schema": "ds02.f7.fresh079.actual-xmf.full601.render-binding.v1",
        "scope_id": "root_followup_079_actual_xmf_render_schema_closure_v1",
        "family_id": "F7", "case_id": case_id, "physical_case_id": case_id,
        "canonical_owner": request.get("canonical_owner"),
        "canonical_owner_sha256": request.get("canonical_owner_sha256"),
        "canonical_physical_binding_sha256": q,
        "producer_physical_condition_sha256": q,
        "producer_scope_schema": SCOPE_SCHEMA,
        "source_plan_condition_sha256": source_plan,
        "canonical_equals_source_plan_claim": False,
        "root411_xmf_request": str(request_path.resolve()),
        "root411_xmf_request_sha256": sha256_metadata(request_path),
        "root411_xmf_binding": str(binding_path.resolve()),
        "root411_xmf_binding_sha256": sha256_metadata(binding_path),
        "xmf_execution_receipt": str(receipt_path.resolve()),
        "xmf_execution_receipt_sha256": receipt_sha,
        "xmf_status": "completed/0",
        "manifest": str(manifest_path.resolve()), "manifest_sha256": manifest_sha,
        "xdmf": str(xmf_path.resolve()), "xdmf_sha256": xmf_sha,
        "xmf_shape_contract": xdmf_shape,
        "expected_frames": 601, "expected_native_frames": 601,
        "expected_particles": 70179,
        "expected_counts": request["expected_counts"],
        "trajectory_h5_read_by_adapter": False,
        "future_render_hashes_null": True,
        "render_output_sha256": None,
        "render_status": "disabled_pending_root_review",
        "source_only": True,
    }
    output.mkdir(parents=True, exist_ok=True)
    dump_json(render_binding_path, render_binding)
    conversion_dependency = request.get("conversion_dependency")
    if not isinstance(conversion_dependency, dict):
        raise AdapterError(f"Root411 conversion dependency missing for {case_id}")
    h5_path = Path(str(conversion_dependency.get("output_hdf5")))
    h5_sha = require_hex(conversion_dependency.get("output_sha256"), f"{case_id} producer H5 attestation")
    additions = [request_path, binding_path, receipt_path, manifest_path, xmf_path,
                 render_binding_path, RENDERER, ROOT142_LAUNCH, ROOT142_POLICY,
                 RESOURCE_APPROVAL, PYTHON]
    files, hashes, provenance = inherited_input_closure(request, additions)
    if str(h5_path.resolve()) not in hashes:
        if not h5_path.is_file():
            raise AdapterError(f"producer H5 path is missing for {case_id}: {h5_path}")
        files.append(str(h5_path.resolve()))
        hashes[str(h5_path.resolve())] = h5_sha
        provenance[str(h5_path.resolve())] = "producer_attested:conversion-report.output_sha256; adapter_did_not_read_h5"
    else:
        if hashes[str(h5_path.resolve())] != h5_sha:
            raise AdapterError(f"Root411 H5 attestation differs for {case_id}")
        provenance[str(h5_path.resolve())] = "producer_attested:conversion-report.output_sha256; adapter_did_not_read_h5"
    if set(files) != set(hashes) or set(files) != set(provenance):
        raise AdapterError(f"render closure is not exact for {case_id}")
    render_request = {
        "schema": "ds02.f7.fresh079.actual-xmf.full601.render-request.v1",
        "scope_id": "root_followup_079_actual_xmf_render_schema_closure_v1",
        "family_id": "F7", "case_id": case_id, "physical_case_id": case_id,
        "attempt_id": render_attempt,
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2,
        "launch_owner": "root", "model_profile": "gpt-5.6-luna/max",
        "cwd": "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab",
        "worktree_root": "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics",
        "command": render_command(manifest_path),
        "output_directory_contract": "{attempt_root}/render",
        "manifest": str(manifest_path.resolve()), "manifest_sha256": manifest_sha,
        "xdmf": str(xmf_path.resolve()), "xdmf_sha256": xmf_sha,
        "xmf_dependency": {
            "request": str(request_path.resolve()), "request_sha256": sha256_metadata(request_path),
            "binding": str(binding_path.resolve()), "binding_sha256": sha256_metadata(binding_path),
            "receipt": str(receipt_path.resolve()), "receipt_sha256": receipt_sha,
            "manifest": str(manifest_path.resolve()), "manifest_sha256": manifest_sha,
            "xdmf": str(xmf_path.resolve()), "xdmf_sha256": xmf_sha,
            "status": "completed/0",
        },
        "conversion_dependency": {
            "status": "completed/0", "report": request.get("conversion_dependency", {}).get("report"),
            "report_sha256": request.get("conversion_dependency", {}).get("report_sha256"),
            "output_hdf5": str(h5_path.resolve()), "output_sha256": h5_sha,
            "output_sha_origin": "producer_attested",
        },
        "producer_conversion_schema": CONVERSION_SCHEMA,
        "producer_scope_schema": SCOPE_SCHEMA,
        "producer_physical_condition_sha256": q,
        "canonical_physical_binding_sha256": q,
        "source_plan_condition_sha256": source_plan,
        "canonical_equals_source_plan_claim": False,
        "expected_frames": 601, "expected_native_frames": 601,
        "expected_particles": 70179, "expected_counts": request["expected_counts"],
        "xmf_shape_contract": xdmf_shape,
        "native_bounds_policy": "Root023 scans native positions over all saved frames; no fixed camera/domain bounds",
        "renderer_source": str(RENDERER), "renderer_source_sha256": sha256_metadata(RENDERER),
        "root142_entry": str(ROOT142_LAUNCH), "root142_entry_sha256": sha256_metadata(ROOT142_LAUNCH),
        "future_outputs": {
            "execution_receipt": "{attempt_root}/execution-receipt.json",
            "execution_receipt_sha256": None,
            "contact_pages": "{attempt_root}/render/contact-page-*.png",
            "render_manifest": "{attempt_root}/render/paraview-full-animation-report.json",
            "render_manifest_sha256": None,
        },
        "input_files": files, "input_sha256": hashes,
        "input_hash_provenance": provenance,
        "estimated_storage_bytes": 8589934592,
        "max_wall_seconds": 7200,
        "root_dataset_inventory_profile": request.get("root_dataset_inventory_profile"),
        "root_inventory_policy_source_sha256": request.get("root_inventory_policy_source_sha256"),
        "resource_window_sha256": request.get("resource_window_sha256"),
        "disabled": True, "launch": False, "launch_allowed": False,
        "execution_allowed": False, "source_only": True,
        "future_hashes_null": True,
        "status": "actual_xmf_bound_disabled_pending_root_review",
        "disabled_reason": "Disabled until Root reviews actual XMF metadata and explicitly enables Root023 full601 rendering.",
        "independent_case_count_increment": 0,
        "arrays_read": False, "h5_read": False, "jobs_started": False,
        "shared_state_written": False,
        "precision_status": "not_accepted", "visual_acceptance": "pending Root023 review",
    }
    dump_json(render_request_path, render_request)
    return {
        "case_id": case_id, "attempt_id": attempt_id, "render_attempt_id": render_attempt,
        "xmf_receipt": str(receipt_path.resolve()), "xmf_receipt_sha256": receipt_sha,
        "manifest": str(manifest_path.resolve()), "manifest_sha256": manifest_sha,
        "xdmf": str(xmf_path.resolve()), "xdmf_sha256": xmf_sha,
        "producer_physical_condition_sha256": q, "source_plan_condition_sha256": source_plan,
        "render_binding": str(render_binding_path.resolve()),
        "render_request": str(render_request_path.resolve()),
        "render_output_sha256": None, "requests_disabled": True,
        "arrays_read": False, "h5_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root411-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root411 = args.root411_dir.expanduser().resolve()
    data_root = args.data_root.expanduser().resolve()
    output = args.output_dir.expanduser().resolve()
    if not root411.is_dir() or not data_root.is_dir():
        raise SystemExit("Root411/data root must be existing directories")
    require_file(RENDERER, "Root023 renderer")
    require_file(ROOT142_LAUNCH, "Root142 entry")
    require_file(ROOT142_POLICY, "Root142 policy")
    require_file(RESOURCE_APPROVAL, "resource approval")
    require_file(PYTHON, "approved Python")
    rows = [bind_case(root411, data_root, output, case_id) for case_id in CASES]
    manifest = {
        "schema": "ds02.f7.fresh079.actual-xmf-bound-render-manifest.v1",
        "scope_id": "root_followup_079_actual_xmf_render_schema_closure_v1",
        "family_id": "F7", "case_count": len(rows), "cases": rows,
        "root411_xmf_completed0_count": len(rows),
        "render_requests_disabled": True, "future_render_hashes_null": True,
        "xmf_shape_contract": "metadata checked: every frame Geometry/velocity=N 3, scalar=N; particle axis retained",
        "renderer": "Root023 native renderer with automatic all-saved-frame native bounds",
        "arrays_read": False, "h5_read": False, "scientific_payloads_read_or_hashed": False,
        "jobs_started": False, "shared_state_written": False, "case_increment": 0,
        "claim_boundary": "Actual Root411 XMF metadata is bound; Root023 render remains disabled and no visual, Q-N, precision, or production claim is made.",
    }
    dump_json(output / "actual-xmf-bound-render-manifest.json", manifest)
    print(json.dumps({"case_count": len(rows), "completed_xmf": len(rows),
                      "render_requests_disabled": True,
                      "manifest": str(output / 'actual-xmf-bound-render-manifest.json')}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AdapterError as exc:
        raise SystemExit(f"fresh079 adapter error: {exc}")
