#!/usr/bin/env python3
"""Static validation for the F1 fresh089 typed->XMF->Root023 source handoff.

This validator reads only text/JSON/XML/source metadata.  It deliberately never
opens a scientific array, future H5, BI4, CSV, VTK, NPY, or NPZ artifact.
"""
from __future__ import annotations
import argparse, ast, hashlib, json
from pathlib import Path

SCIENCE = {".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".npy", ".npz"}
CASES = [
    "F1_STAGE1_DUAL_H240_DP020",
    "F1_STAGE1_DUAL_H240_DP020_VX010",
    "F1_STAGE1_DUAL_H280_DP020",
    "F1_STAGE1_DUAL_H320_DP020",
    "F1_STAGE1_ECC_H120_DP010",
    "F1_STAGE1_ECC_H140_DP010",
    "F1_STAGE1_ECC_H160_DP010",
    "F1_STAGE1_ECC_H180_DP010",
]


def fail(message: str) -> None:
    raise SystemExit(f"fresh089 validation failed: {message}")


def ensure(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid JSON {path}: {exc}")
    return value


def sha(path: Path) -> str:
    ensure(path.suffix.lower() not in SCIENCE, f"validator would read scientific artifact {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_file(raw: str, label: str) -> Path:
    path = Path(raw)
    ensure(path.is_file(), f"{label} missing: {path}")
    ensure(path.suffix.lower() not in SCIENCE, f"{label} is scientific artifact: {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    package = args.package.resolve()
    ensure(package.is_dir(), f"package missing: {package}")
    ensure(package.name.endswith("089_f1_actual_typed_xmf_root023_render_v1"), "unexpected package name")

    files = [p for p in package.rglob("*") if p.is_file()]
    ensure(files, "package is empty")
    for path in files:
        ensure(path.suffix.lower() not in SCIENCE, f"package contains scientific artifact {path}")
    for path in package.rglob("*.json"):
        load(path)
    for path in [package / "workers/export_xmf_legacy_aware.py", package / "workers/render_native023.py"]:
        ensure(path.is_file(), f"worker missing {path}")
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            fail(f"worker syntax error {path}: {exc}")

    up = package / "upstream/fresh088"
    ensure(up.is_dir(), "fresh088 upstream evidence missing")
    metadata = load(package / "metadata/root230-policy.json")
    ensure(metadata.get("fresh_id") == "fresh089", "root230 metadata fresh id")
    dispatch = metadata.get("dispatch", {})
    ensure(dispatch.get("profile") == "root_home_floor_no_legacy_dataset_walk_native_v1", "Root230 profile drift")
    ensure(dispatch.get("root_owned") is True, "Root230 must remain root-owned")

    xmf_files = sorted((package / "bindings/xmf").glob("*.json"))
    render_files = sorted((package / "bindings/render").glob("*.json"))
    xmf_req_files = sorted((package / "requests/xmf").glob("*.json"))
    render_req_files = sorted((package / "requests/render").glob("*.json"))
    ensure(len(xmf_files) == len(render_files) == len(xmf_req_files) == len(render_req_files) == 8, "must have exactly eight downstream rows")
    ensure({p.stem.removesuffix(".legacy-aware-binding") for p in xmf_files} == set(CASES), "XMF case set mismatch")
    ensure({p.stem.removesuffix(".native023-render-binding") for p in render_files} == set(CASES), "render case set mismatch")

    for case in CASES:
        up_bind_path = up / "bindings" / f"{case}.typed-nvme-binding.json"
        up_owner_path = up / "owners" / f"{case}.typed-owner.json"
        up_req_path = up / "requests" / f"{case}.full-native-typed-nvme.request.json"
        canonical_path = package / "source/owners" / f"{case}.actual-root283.owner.json"
        legacy_path = package / "owners" / f"{case}.legacy-owner-scope.v0.json"
        sidecar_path = package / "provenance" / f"{case}.canonical-physical-binding.json"
        preflight_path = package / "metadata/legacy-scope-preflight" / f"{case}.json"
        adapter_path = package / "owners" / f"{case}.typed-owner-xmf-adapter.json"
        typed_bind_path = package / "bindings/typed-legacy" / f"{case}.typed-nvme-binding.json"
        typed_req_path = package / "requests/typed-legacy" / f"{case}.full-native-typed-nvme-legacy.request.json"
        xmf_path = package / "bindings/xmf" / f"{case}.legacy-aware-binding.json"
        render_path = package / "bindings/render" / f"{case}.native023-render-binding.json"
        xr_path = package / "requests/xmf" / f"{case}.root193-xmf.request.json"
        rr_path = package / "requests/render" / f"{case}.root194-render.request.json"
        for path in (up_bind_path, up_owner_path, up_req_path, canonical_path, legacy_path, sidecar_path, preflight_path, adapter_path, typed_bind_path, typed_req_path, xmf_path, render_path, xr_path, rr_path):
            ensure(path.is_file(), f"missing case evidence {path}")
        up_bind = load(up_bind_path); up_owner = load(up_owner_path); up_req = load(up_req_path)
        canonical = load(canonical_path); legacy = load(legacy_path); sidecar = load(sidecar_path); preflight = load(preflight_path); adapter = load(adapter_path)
        typed_bind = load(typed_bind_path); typed_req = load(typed_req_path)
        xb = load(xmf_path); rb = load(render_path); xr = load(xr_path); rr = load(rr_path)

        expected_frames = int(up_bind["expected_frames"])
        expected_particles = int(up_bind["expected_particles"])
        actual_counts = up_bind.get("actual_native_frame0_qa", {}).get("actual_particle_counts")
        ensure(isinstance(actual_counts, dict), f"{case}: actual counts missing")
        ensure(expected_particles == sum(int(actual_counts.get(k, 0)) for k in ("fixed", "moving", "floating", "fluid")), f"{case}: expected particle count is not actual frame0 count")
        ensure(int(up_bind["actual_native_observed_frame_file_count"]) == expected_frames, f"{case}: native frame inventory drift")
        ensure(expected_frames == (401 if case.startswith("F1_STAGE1_DUAL") else 161), f"{case}: unexpected dynamic frame count")
        ensure(float(up_bind["save_interval_s"]) == 0.01, f"{case}: save interval drift")
        ensure(int(up_bind["expected_dimension"]) == 3, f"{case}: dimension drift")
        ensure(up_bind["typed_output_sha256"] is None and up_bind["typed_conversion_report_sha256"] is None and up_bind["typed_execution_receipt_sha256"] is None, f"{case}: upstream typed future hash was filled")
        ensure(up_bind["legacy_h5_physical_condition_sha256"] is None, f"{case}: legacy scope was fabricated in immutable fresh088")

        ensure("physical_binding" not in legacy, f"{case}: legacy owner contains explicit canonical physical_binding")
        ensure(legacy.get("physical_condition_scope_schema") == "legacy-owner-scope.v0", f"{case}: legacy owner schema")
        ensure(preflight.get("status") == "metadata_only_preflight_passed" and preflight.get("scope_schema") == "legacy-owner-scope.v0", f"{case}: legacy preflight failed")
        ensure(preflight.get("owner_metadata") == str(legacy_path) and preflight.get("owner_metadata_sha256") == sha(legacy_path), f"{case}: legacy preflight owner closure")
        ensure(preflight.get("scope_sha256") == typed_bind["legacy_h5_physical_condition_sha256"], f"{case}: preflight scope hash not bound")
        ensure(typed_bind["strict_canonical_validation_granted"] is False, f"{case}: strict canonical validation was fabricated")
        ensure(sidecar["canonical_physical_binding"] == canonical["physical_binding"], f"{case}: canonical physical binding provenance changed")
        ensure(sidecar["canonical_physical_binding_sha256"] == up_bind["canonical_physical_binding_sha256"], f"{case}: canonical sidecar SHA drift")
        ensure(preflight.get("actual_converter_execution") is False and preflight.get("arrays_read") is False, f"{case}: preflight is not metadata-only")
        ensure(typed_bind["typed_output_sha256"] is None and typed_bind["typed_conversion_report_sha256"] is None and typed_bind["typed_execution_receipt_sha256"] is None, f"{case}: revised typed future hash filled")
        ensure(typed_req["disabled"] is True and typed_req["execution_allowed"] is False and typed_req["launch"] is False and typed_req["launch_owner"] == "root", f"{case}: revised typed request enabled")
        ensure(typed_req["legacy_owner_metadata"] == str(legacy_path) and typed_req["legacy_owner_metadata_sha256"] == sha(legacy_path), f"{case}: revised typed owner metadata closure")
        ensure("--owner-metadata" in typed_req["command"] and typed_req["command"][typed_req["command"].index("--owner-metadata") + 1] == str(legacy_path), f"{case}: converter command does not use legacy owner")
        ensure(typed_req["attempt_id"].endswith("-089-legacy-scope"), f"{case}: revised typed attempt identity")
        for raw, expected in typed_req["input_sha256"].items():
            path = safe_file(raw, f"{case} typed input")
            ensure(sha(path) == expected, f"{case}: typed input SHA mismatch {path}")
        ensure(not any(Path(str(p)).suffix.lower() in SCIENCE for p in typed_req["input_files"]), f"{case}: typed immediate input includes science array")

        canonical_sha = sha(canonical_path)
        ensure(adapter["source_owner"] == str(canonical_path), f"{case}: adapter source owner does not bind canonical source")
        ensure(adapter["source_owner_sha256"] == canonical_sha, f"{case}: adapter source owner SHA mismatch")
        ensure(adapter["canonical_owner"] == str(canonical_path), f"{case}: adapter canonical owner drift")
        ensure(adapter["canonical_owner_sha256"] == canonical_sha, f"{case}: adapter canonical SHA mismatch")
        ensure(adapter["physical_condition_sha256"] == canonical["physical_condition_sha256"], f"{case}: adapter physical condition drift")
        ensure(adapter["converter_owner_metadata"] == str(legacy_path) and adapter["converter_owner_metadata_sha256"] == sha(legacy_path), f"{case}: adapter legacy owner closure")
        ensure(adapter["converter_legacy_scope_sha256"] == preflight["scope_sha256"], f"{case}: adapter legacy scope hash")
        ensure(adapter.get("strict_canonical_validation_granted") is False, f"{case}: adapter strict validation fabricated")
        ensure(adapter.get("source_only") is True and adapter.get("execution_allowed") is False and adapter.get("launch_allowed") is False, f"{case}: adapter is executable")
        ensure(sha(up_owner_path) == adapter["upstream_fresh088_typed_owner_sha256"], f"{case}: upstream owner SHA mismatch")
        ensure(sha(up_bind_path) == adapter["upstream_fresh088_binding_sha256"], f"{case}: upstream binding SHA mismatch")

        # XMF binding: actual native evidence is complete, typed evidence is deliberately future/null.
        ensure(xb["fresh_id"] == "fresh089" and xb["case_id"] == case, f"{case}: XMF identity")
        ensure(xb["canonical_owner"] == str(canonical_path) and xb["canonical_owner_sha256"] == canonical_sha, f"{case}: XMF canonical owner closure")
        ensure(xb["typed_owner"] == str(adapter_path) and xb["typed_owner_sha256"] == sha(adapter_path), f"{case}: XMF adapter closure")
        ensure(xb["canonical_physical_condition_sha256"] == canonical["physical_condition_sha256"], f"{case}: XMF condition drift")
        ensure(xb["canonical_physical_binding_sha256"] == up_bind["canonical_physical_binding_sha256"], f"{case}: XMF physical binding drift")
        ensure(xb["legacy_h5_physical_condition_sha256"] == preflight["scope_sha256"] and xb["legacy_h5_physical_condition_scope"]["schema"] == "legacy-owner-scope.v0", f"{case}: XMF legacy scope invalid")
        ensure(xb["strict_canonical_validation_granted"] is False and xb["legacy_owner_metadata"] == str(legacy_path), f"{case}: XMF strict/legacy provenance")
        ensure(xb["fresh089_typed_binding"] == str(typed_bind_path) and xb["fresh089_typed_binding_sha256"] == sha(typed_bind_path), f"{case}: XMF revised typed binding closure")
        ensure(int(xb["expected_frames"]) == expected_frames and int(xb["expected_particles"]) == expected_particles, f"{case}: XMF dynamic metadata drift")
        ensure(xb["expected_dimension"] == 3 and xb["future_hashes_null"] is True, f"{case}: XMF future/dimension contract")
        ensure(xb["root193_xmf"]["output_dir"].endswith("/xdmf"), f"{case}: XMF output is not a child directory")
        ensure(xb["root194_render"]["output_dir"].endswith("/render"), f"{case}: render output is not a child directory")
        ensure(xb["typed_output_sha256"] is None and xb["typed_conversion_report_sha256"] is None and xb["typed_execution_receipt_sha256"] is None, f"{case}: XMF typed future hashes filled")
        ensure(xb["actual_frame0_qa"]["status"] == "completed/0" and xb["actual_frame0_qa"]["passed"] is True, f"{case}: actual frame0 QA not bound")
        ensure(xb["native_identity_contract"]["expected_dimension"] == 3, f"{case}: native identity dimension")
        ensure(xb["native_identity_contract"]["dynamic_shapes"]["position"] == ["frames", "particles", 3], f"{case}: position shape contract")
        ensure(xb["native_identity_contract"]["dynamic_shapes"]["velocity"] == ["frames", "particles", 3], f"{case}: velocity shape contract")
        ensure(xb["owner_scopes"]["canonical"]["sha256"] == canonical["physical_condition_sha256"], f"{case}: canonical scope missing")
        ensure(xb["owner_scopes"]["legacy_h5"]["schema"] == "legacy-owner-scope.v0", f"{case}: legacy scope missing")

        # XMF request: strict, disabled, Root-owned, and no scientific file in immediate input closure.
        ensure(xr["fresh_id"] == "fresh089" and xr["case_id"] == case, f"{case}: XMF request identity")
        ensure(xr["disabled"] is True and xr["launch"] is False and xr["execution_allowed"] is False and xr["source_only"] is True, f"{case}: XMF request enabled")
        ensure(xr["launch_owner"] == "root" and xr["cpu_task_kind"] == "conversion", f"{case}: XMF owner/task kind")
        ensure(xr["binding"] == str(xmf_path) and xr["binding_sha256"] == sha(xmf_path), f"{case}: XMF request binding closure")
        ensure(xr["typed_binding"] == str(typed_bind_path) and xr["typed_binding_sha256"] == sha(typed_bind_path), f"{case}: XMF request revised typed closure")
        ensure(xr["legacy_owner_metadata"] == str(legacy_path) and xr["legacy_owner_metadata_sha256"] == sha(legacy_path), f"{case}: XMF request legacy closure")
        ensure(xr["command"][0] == str(Path(xr["command"][0])) and "--binding" in xr["command"] and "--output-dir" in xr["command"], f"{case}: XMF command keys")
        ensure(xr["command"][-1] == "{attempt_root}/xdmf", f"{case}: XMF child output command")
        ensure(xr["future_input_sha256"] is None and all(Path(str(p)).suffix.lower() in SCIENCE or str(p).endswith(".json") for p in xr["future_input_files"]), f"{case}: XMF future input contract")
        ensure(xr["root230_dispatch"]["profile"] == "root_home_floor_no_legacy_dataset_walk_native_v1", f"{case}: XMF Root230 profile")
        ensure(int(xr["estimated_storage_bytes"]) == 8589934592 and int(xr["max_wall_seconds"]) == 1800, f"{case}: XMF resource profile")
        for raw, expected in xr["input_sha256"].items():
            path = safe_file(raw, f"{case} XMF input")
            ensure(sha(path) == expected, f"{case}: XMF input SHA mismatch {path}")
        ensure(not any(Path(str(p)).suffix.lower() in SCIENCE for p in xr["input_files"]), f"{case}: XMF immediate input includes science array")

        # Render binding/request: XMF manifest/H5 stay future null until Root completes XMF and typed conversion.
        ensure(rb["fresh_id"] == "fresh089" and rb["case_id"] == case, f"{case}: render identity")
        ensure(rb["xmf_binding"] == str(xmf_path) and rb["xmf_binding_sha256"] == sha(xmf_path), f"{case}: render XMF closure")
        ensure(rb["xmf_manifest_sha256"] is None and rb["xdmf_sha256"] is None and rb["typed_output_sha256"] is None, f"{case}: render future hash filled")
        ensure(int(rb["expected_frames"]) == expected_frames and int(rb["expected_particles"]) == expected_particles and rb["expected_dimension"] == 3, f"{case}: render dynamic metadata")
        ensure(rb["camera_bounds_policy"].startswith("native023 auto-all-frame"), f"{case}: render camera policy")
        ensure(rb["source_only"] is True and rb["execution_allowed"] is False and rb["launch_allowed"] is False, f"{case}: render enabled")
        ensure(rr["fresh_id"] == "fresh089" and rr["case_id"] == case, f"{case}: render request identity")
        ensure(rr["disabled"] is True and rr["launch"] is False and rr["execution_allowed"] is False and rr["source_only"] is True and rr["launch_owner"] == "root", f"{case}: render request enabled/owner")
        ensure(rr["binding"] == str(render_path) and rr["binding_sha256"] == sha(render_path), f"{case}: render binding closure")
        required_env = {"VTK_SMP_MAX_THREADS=2", "LP_NUM_THREADS=2", "LIBGL_ALWAYS_SOFTWARE=1", "MESA_LOADER_DRIVER_OVERRIDE=llvmpipe", "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json", "VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow", "QT_QPA_PLATFORM=offscreen", "OMP_NUM_THREADS=2"}
        ensure(required_env <= set(rr["command"]), f"{case}: software renderer environment incomplete")
        ensure("--force-offscreen-rendering" in rr["command"] and "--manifest" in rr["command"] and "--output-dir" in rr["command"], f"{case}: renderer command contract")
        ensure(rr["command"][-1] == "{attempt_root}/render", f"{case}: renderer child output command")
        ensure(rr["future_input_sha256"] is None, f"{case}: renderer future input hash filled")
        for raw, expected in rr["input_sha256"].items():
            path = safe_file(raw, f"{case} render input")
            ensure(sha(path) == expected, f"{case}: render input SHA mismatch {path}")
        ensure(not any(Path(str(p)).suffix.lower() in SCIENCE for p in rr["input_files"]), f"{case}: render immediate input includes science array")

    result = {
        "schema": "ds02.f1.fresh089.static-source-validation.v1",
        "fresh_id": "fresh089",
        "case_count": 8,
        "xmf_request_count": 8,
        "render_request_count": 8,
        "actual_native_frame0_qa_reused": 8,
        "fresh088_canonical_typed_negative_or_unsettled_count": 8,
        "legacy_scope_preflight_passed_count": 8,
        "typed_conversion_actual_count": 0,
        "xmf_actual_count": 0,
        "render_actual_count": 0,
        "future_scientific_hashes_filled": False,
        "dynamic_counts_source": "fresh088 actual Root307 frame0 QA metadata; no source rounding",
        "canonical_source_legacy_scopes_distinct": True,
        "software_only_renderer": True,
        "raw_arrays_read": False,
        "jobs_launched": False,
        "shared_state_modified": False,
        "status": "passed_source_only_disabled",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
