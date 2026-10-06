#!/usr/bin/env python3
"""Generic M090 identity adapter for the unchanged F5 fresh138 bed audit.

Only the loaded original worker's module-global CASE_ID is rebound to the
producer-suffixed case ID.  The original numeric/profile/threshold code and all
science inputs remain untouched.  ``--check`` performs the original worker's
metadata gate and lists BI4 frame names only; it never opens H5/BI4/CSV/DAT/VTK.
"""
from __future__ import annotations
import argparse, copy, hashlib, importlib.util, json
from pathlib import Path
from typing import Any

BINDING_SCHEMA = "ds02.f5.c082s1.full-event-bed-audit-binding.fresh138.v1"
ADAPTER_SCHEMA = "ds02.f5.c082s1.next34.case-rebind-adapter.fresh174.v1"
BASE_CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
PRODUCER_CASE_PREFIX = BASE_CASE_ID + "_M090_T"
PHYSICAL_PREFIX = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M090_T"
ORIGINAL_WORKER = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_138_stage1_f5_remaining10_full801_downstream_disabled_v1/workers/bed_audit_full801_fresh138.py")
ORIGINAL_WORKER_SHA = "89be048da1df6bae49627308edb35a8a1936bc0888259cb5ab3d195307b550e2"
SCIENCE_SUFFIXES = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz"}

def require(ok: bool, msg: str) -> None:
    if not ok:
        raise ValueError(msg)
def sha256_file(path: Path) -> str:
    require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"source hash forbidden for science payload: {path}")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()
def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value
def is_bound(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and not value.startswith("<")
def load_original():
    require(sha256_file(ORIGINAL_WORKER) == ORIGINAL_WORKER_SHA, "original fresh138 worker drifted")
    spec = importlib.util.spec_from_file_location("fresh138_original_fresh174", ORIGINAL_WORKER)
    require(spec is not None and spec.loader is not None, "cannot load original worker")
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    require(getattr(original, "CASE_ID", None) == BASE_CASE_ID, "original worker base CASE_ID changed")
    return original

def validate_binding(binding_path: Path, run_original_metadata_gate: bool = True) -> dict[str, Any]:
    binding = load_json(binding_path)
    require(binding.get("schema") == BINDING_SCHEMA, "fresh138 schema mismatch")
    case_id = str(binding.get("case_id", ""))
    require(case_id.startswith(PRODUCER_CASE_PREFIX) and case_id.endswith("_NEXT34"), "M090 producer case identity mismatch")
    require(binding.get("producer_case_id") == case_id, "producer_case_id mismatch")
    physical = str(binding.get("physical_case_id", ""))
    require(physical.startswith(PHYSICAL_PREFIX), "M090 physical identity mismatch")
    require(binding.get("execution_allowed") is False and binding.get("disabled") is True, "bed request is not disabled")
    require(binding.get("launch_allowed") is False and binding.get("solver_allowed") is False, "disabled launch flags changed")
    require(binding.get("full801_authorized") is False, "full801 gate was enabled")
    require(binding.get("native_bed_marker_mk") == 50 and binding.get("source_bed_marker_mkbound") == 40, "Mk50/mkbound40 mapping changed")
    require(binding.get("expected_dimension") == 3 and binding.get("expected_frames") == 801, "3D/801 contract changed")
    require((binding.get("expected_particle_axis"), binding.get("expected_fluid_particles"), binding.get("expected_fixed_particles"), binding.get("expected_moving_particles")) == (194427, 31658, 158559, 4210), "actual producer counts changed")
    canonical = str(binding.get("physical_condition_sha256", ""))
    source_plan_role = str(binding.get("source_plan_physical_condition_sha256", ""))
    legacy = str(binding.get("source_h5_physical_condition_sha256", ""))
    require(is_bound(canonical) and is_bound(source_plan_role) and is_bound(legacy), "scope hash not bound")
    require(canonical != source_plan_role and canonical != legacy, "canonical/source scopes collapsed")
    semantics = binding.get("physical_condition_hash_semantics", {})
    require(semantics.get("canonical_owner_sha256") == canonical, "canonical semantics missing")
    require(semantics.get("source_h5_sha256") == legacy, "legacy semantics missing")
    require(semantics.get("source_h5_scope_schema") == "legacy-owner-scope.v0", "legacy scope schema changed")
    require(semantics.get("source_h5_scope_status") == "legacy_incomplete; no cross-resolution physical claim", "legacy scope status changed")
    # Source_Def is a metadata source and is the explicit source-plan role for
    # this adapter.  The actual1008 XMF producer declaration is retained separately.
    source_def = Path(str(binding["source_definition"])); require(source_def.is_file() and source_def.suffix.lower()==".xml", "Source_Def missing")
    require(sha256_file(source_def) == binding.get("source_definition_sha256"), "Source_Def SHA mismatch")
    source_plan = Path(str(binding["source_plan_file"])); require(source_plan.is_file() and source_plan.suffix.lower()==".json", "source plan missing")
    require(sha256_file(source_plan) == binding.get("source_plan_file_sha256"), "source plan file SHA mismatch")
    require(source_plan_role == binding.get("source_definition_sha256"), "source-plan role is not explicit Source_Def SHA")
    # All producer metadata references are JSON/XML only.  H5/BI4/DAT/CSV/VTK
    # values are producer attestations and are never opened or rehashed here.
    metadata_refs = (
        ("gencase_receipt", "gencase_receipt_sha256"),
        ("gencase_prepared_report", "gencase_prepared_report_sha256"),
        ("initial_qa_receipt", "initial_qa_receipt_sha256"),
        ("initial_qa_report", "initial_qa_report_sha256"),
        ("full_native_receipt", "full_native_receipt_sha256"),
        ("full_typed_conversion_report", "full_typed_conversion_report_sha256"),
        ("canonical_generated_xml", "canonical_generated_xml_sha256"),
        ("xmf_manifest", "xmf_manifest_sha256"),
        ("xmf_receipt", "xmf_receipt_sha256"),
        ("xdmf", "xdmf_sha256"),
    )
    for path_key, hash_key in metadata_refs:
        path = Path(str(binding.get(path_key, "")))
        require(path.is_file() and path.suffix.lower() not in SCIENCE_SUFFIXES, f"{path_key} is not a metadata file")
        require(sha256_file(path) == binding.get(hash_key), f"{path_key} SHA mismatch")
    gencase = load_json(Path(str(binding["gencase_receipt"])))
    require(gencase.get("status") in {"completed", "completed/0"} and gencase.get("returncode") == 0, "GenCase receipt not completed/0")
    require(gencase.get("request", {}).get("case_id", gencase.get("case_id")) == case_id, "GenCase case identity mismatch")
    require(Path(str(gencase.get("output_root"))).resolve() == Path(str(binding["gencase_output_root"])).resolve(), "GenCase root mismatch")
    prepared = load_json(Path(str(binding["gencase_prepared_report"])))
    require(prepared.get("case_id") == case_id and prepared.get("actual_total_particles") == 194427, "prepared report mismatch")
    counts = prepared.get("generated_xml_particle_counts", {})
    require({k:int(counts.get(k, -1)) for k in ("fixed","moving","floating","fluid")} == {"fixed":158559,"moving":4210,"floating":0,"fluid":31658}, "prepared counts mismatch")
    require(prepared.get("xml_sha256") == binding.get("canonical_generated_xml_sha256"), "generated XML attestation mismatch")
    qa = load_json(Path(str(binding["initial_qa_receipt"])))
    require(qa.get("status") == "completed" and qa.get("returncode") == 0, "initial QA not completed/0")
    require(Path(str(qa.get("output_root"))).resolve() == Path(str(binding["initial_qa_output_root"])).resolve(), "initial QA output root mismatch")
    placement = load_json(Path(str(binding["initial_qa_report"])))
    require(placement.get("all_basic_placement_checks_pass") is True and placement.get("stage1_basic_placement_proof") == "pass_excluding_numerical_precision", "initial placement proof changed")
    require(placement.get("numerical_precision_result_accepted") is False, "precision negative was changed")
    require(placement.get("actual_counts") == binding.get("actual_counts"), "placement actual counts mismatch")
    bins = placement.get("mk50_coverage", {}).get("six_segment_bins", [])
    require(len(bins) == 6 and all(int(row.get("central_abs_y_le_0p01_surface_half_dp_count",0)) > 0 for row in bins), "central Mk50 coverage missing")
    native = load_json(Path(str(binding["full_native_receipt"])))
    require(native.get("status") == "completed" and native.get("returncode") == 0, "native receipt not completed/0")
    require(native.get("request", {}).get("case_id", native.get("case_id")) == case_id, "native case identity mismatch")
    require(Path(str(native.get("output_root"))).resolve() == Path(str(binding["full_native_output_root"])).resolve(), "native output root mismatch")
    command = native.get("command", [])
    require(any(str(v).startswith("-tmax:16") for v in command) and any(str(v).startswith("-tout:0.02") for v in command), "native 16s/.02 contract mismatch")
    data_root = Path(str(binding["full_native_data_root"])); require(data_root.is_dir(), "native data root missing")
    require(sorted(p.name for p in data_root.glob("Part_*.bi4")) == [f"Part_{i:04d}.bi4" for i in range(801)], "native frame sequence mismatch")
    conversion = load_json(Path(str(binding["full_typed_conversion_report"])))
    require(conversion.get("conversion_status", conversion.get("status")) == "completed" and conversion.get("frames") == 801 and conversion.get("particles") == 194427, "typed conversion dimensions mismatch")
    dim = conversion.get("solver_dimension", {})
    require((dim.get("solver_dimension", dim.get("value", 3)) if isinstance(dim, dict) else dim) == 3, "typed conversion not 3D")
    identity = conversion.get("typed_identity", {})
    role_counts = {}
    for block in identity.get("blocks", []):
        if isinstance(block, dict): role_counts[str(block.get("tag", ""))] = role_counts.get(str(block.get("tag", "")), 0) + int(block.get("count", 0))
    require(role_counts.get("fixed") == 158559 and role_counts.get("moving") == 4210 and role_counts.get("fluid") == 31658, "typed identity counts mismatch")
    require(50 in set(identity.get("observed_mks", [])) and {0,1,3}.issubset(set(identity.get("observed_types", []))), "typed Mk/type identity incomplete")
    manifest = load_json(Path(str(binding["xmf_manifest"])))
    require(manifest.get("case_id") == case_id and manifest.get("frames") == 801 and manifest.get("particles") == 194427, "XMF dimensions/identity mismatch")
    require(manifest.get("source_h5_sha256") == binding.get("trajectory_h5_sha256"), "XMF H5 producer attestation mismatch")
    require(manifest.get("physical_condition_sha256") == canonical and manifest.get("canonical_physical_condition_sha256") == canonical, "XMF canonical scope mismatch")
    if run_original_metadata_gate:
        original = load_original()
        original.CASE_ID = case_id
        result = original._verify_bound_metadata(binding)
        require(result.get("case_id") == case_id, "original138 metadata gate did not rebind identity")
    return {"case_id":case_id,"physical_case_id":physical,"scope":{"canonical":canonical,"source_plan_role":source_plan_role,"source_h5_legacy":legacy},"counts":binding.get("producer_actual_counts", binding.get("expected_counts")),"metadata_gate":"original138 _verify_bound_metadata passed" if run_original_metadata_gate else "skipped"}

def invoke_original(binding_path: Path, trajectory_h5: Path, xdmf: Path, output_dir: Path) -> int:
    binding = validate_binding(binding_path, run_original_metadata_gate=False)
    original = load_original()
    original.CASE_ID = binding["case_id"]
    with __import__("tempfile").TemporaryDirectory(prefix="f5-fresh174-case-rebind-") as temp:
        temp_binding = Path(temp) / "binding.json"
        temp_binding.write_text(json.dumps(load_json(binding_path), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return int(original.main(["--binding", str(temp_binding), "--trajectory-h5", str(trajectory_h5), "--xdmf", str(xdmf), "--output-dir", str(output_dir)]))

def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--trajectory-h5", type=Path)
    parser.add_argument("--xdmf", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.check:
        binding_dir = Path(__file__).resolve().parents[1] / "bindings"
        reports = [validate_binding(p, run_original_metadata_gate=True) for p in sorted(binding_dir.glob("*.json"))]
        print(json.dumps({"schema":ADAPTER_SCHEMA,"status":"passed","checks":reports,"science_payload_opened_or_hashed":False}, indent=2, sort_keys=True))
        return 0
    if any(v is None for v in (args.binding,args.trajectory_h5,args.xdmf,args.output_dir)):
        parser.error("--binding, --trajectory-h5, --xdmf, and --output-dir are required")
    binding = load_json(args.binding)
    original = load_original(); original.CASE_ID = binding.get("case_id")
    return invoke_original(args.binding, args.trajectory_h5, args.xdmf, args.output_dir)
if __name__ == "__main__":
    raise SystemExit(main())
