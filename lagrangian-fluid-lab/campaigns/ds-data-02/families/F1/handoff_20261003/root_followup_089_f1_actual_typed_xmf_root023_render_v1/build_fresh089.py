#!/usr/bin/env python3
"""Build F1 fresh089 Root307 -> typed -> XMF -> Root023 source handoff.

This builder consumes only JSON/XML/source metadata and already recorded hashes.
It never opens, hashes, copies, or launches any BI4/H5/CSV/VTK/NPY/NPZ array,
solver, converter, GenCase, or renderer job.  All downstream requests are
explicitly disabled for Root review.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import shutil
import subprocess

from pathlib import Path

F1 = Path("/home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
FRESH088 = F1 / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_088_f1_root307_actual_native_qa_typed_nvme_v1"
OLD087 = F1 / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_087_f1_root298_actual_gencase_qa_native_bind_v1"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
GPU_POLICY = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
RESOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
GOAL = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"
PYTHON = INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"
CONVERTER = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_nvme_convert_v1.py"
DIRECT_CONVERTER = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = INTEGRATION / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
PVPYTHON = Path("/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython")
VALIDATOR = Path("/tmp/validate_f1_fresh089.py")
PACKAGE = F1 / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_089_f1_actual_typed_xmf_root023_render_v1"
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
SCIENCE = {".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".npy", ".npz"}


def ensure(value: object, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def load(path: Path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    ensure(isinstance(value, (dict, list)), f"JSON root must be object/list: {path}")
    return value


def sha(path: Path) -> str:
    path = Path(path)
    ensure(path.is_file(), f"cannot hash missing file: {path}")
    ensure(path.suffix.lower() not in SCIENCE, f"scientific array read/hash forbidden: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(relative: str, value: object) -> Path:
    path = PACKAGE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def copy_file(source: Path, relative: str) -> Path:
    source = Path(source)
    ensure(source.is_file(), f"missing source file: {source}")
    ensure(source.suffix.lower() not in SCIENCE, f"scientific source copy forbidden: {source}")
    destination = PACKAGE / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def safe_external(path: Path, label: str) -> Path:
    path = Path(path)
    ensure(path.is_file(), f"{label} missing: {path}")
    ensure(path.suffix.lower() not in SCIENCE, f"{label} is scientific array: {path}")
    return path


def unique_paths(paths: list[Path]) -> list[Path]:
    result = []
    seen = set()
    for path in paths:
        path = Path(path)
        if str(path) not in seen:
            result.append(path)
            seen.add(str(path))
    return result


def copy_upstream() -> None:
    # The upstream bytes are copied as evidence, without rewriting their absolute
    # provenance.  These are all text metadata/source files.
    rows = []
    for directory in [
        "owners", "bindings", "requests", "source/owners", "source/definitions",
        "source/source-plans", "source/gencase-bindings", "metadata/root307",
    ]:
        for source in sorted((FRESH088 / directory).glob("*")):
            if source.is_file() and source.suffix.lower() not in SCIENCE:
                rows.append((source, Path("upstream/fresh088") / directory / source.name))
    rows += [
        (FRESH088 / "metadata/lineage.json", Path("upstream/fresh088/metadata/lineage.json")),
        (FRESH088 / "metadata/root230-policy.json", Path("upstream/fresh088/metadata/root230-policy.json")),
        (FRESH088 / "metadata/typed-candidate-registry.json", Path("upstream/fresh088/metadata/typed-candidate-registry.json")),
    ]
    for source, relative in rows:
        if source.is_file():
            copy_file(source, str(relative))
    for directory in ["source/owners", "source/definitions", "source/source-plans", "source/gencase-bindings"]:
        for source in sorted((FRESH088 / directory).glob("*")):
            if source.is_file() and source.suffix.lower() not in SCIENCE:
                copy_file(source, str(Path(directory) / source.name))
    copy_file(OLD087 / "workers/export_xmf_legacy_aware.py", "workers/export_xmf_legacy_aware.py")
    copy_file(OLD087 / "workers/render_native023.py", "workers/render_native023.py")
    copy_file(VALIDATOR, "validate_source_contract.py")
    copy_file(Path(__file__), "build_fresh089.py")


def load_case(case: str) -> tuple[dict, dict, dict, dict, dict, Path, Path, Path]:
    bind = load(FRESH088 / "bindings" / f"{case}.typed-nvme-binding.json")
    owner = load(FRESH088 / "owners" / f"{case}.typed-owner.json")
    request = load(FRESH088 / "requests" / f"{case}.full-native-typed-nvme.request.json")
    source_owner_path = PACKAGE / "source/owners" / f"{case}.actual-root283.owner.json"
    source_plan_path = PACKAGE / "source/source-plans" / f"{case}.json"
    source_definition_path = PACKAGE / "source/definitions" / f"{case}_Def.xml"
    canonical = load(source_owner_path)
    ensure(canonical.get("case_id") == case, f"canonical owner case mismatch: {case}")
    ensure(source_owner_path.is_file() and source_plan_path.is_file() and source_definition_path.is_file(), f"local source evidence missing: {case}")
    generated_xml = safe_external(Path(bind["generated_xml"]), f"generated XML {case}")
    generated_def = generated_xml.with_name(generated_xml.stem + "_Def.xml")
    safe_external(generated_def, f"generated Def {case}")
    return bind, owner, request, canonical, load(FRESH088 / "source/gencase-bindings" / f"{case}.actual-root283.json"), source_owner_path, source_plan_path, source_definition_path


def legacy_owner_for(case: str, canonical: dict, canonical_path: Path) -> tuple[dict, Path, Path]:
    """Create the converter's explicit legacy-owner metadata without a physical_binding key.

    The full source physical_binding is preserved byte-for-byte in a separate
    provenance sidecar.  Omitting the key intentionally selects the direct
    converter's legacy-owner-scope.v0 path, because fresh088's canonical object
    contains unclassified source-only labels and must not be silently relaxed.
    """
    physical = canonical.get("physical_binding")
    ensure(isinstance(physical, dict), f"canonical physical_binding missing: {case}")
    sidecar = {
        "schema": "ds02.f1.fresh089.canonical-physical-binding-provenance.v1",
        "case_id": case,
        "canonical_owner": str(canonical_path),
        "canonical_owner_sha256": sha(canonical_path),
        "canonical_physical_condition_sha256": canonical["physical_condition_sha256"],
        "canonical_physical_binding_sha256": canonical_sha(physical),
        "canonical_physical_binding": copy.deepcopy(physical),
        "strict_canonical_validation_granted": False,
        "strict_canonical_validation_reason": "fresh088 physical_binding contains unclassified source-only fields; preserved without stripping or reclassifying",
        "source_only": True,
    }
    sidecar_path = write_json(f"provenance/{case}.canonical-physical-binding.json", sidecar)
    # These are exactly the keys accepted by _physical_condition_scope's
    # legacy fallback.  No explicit physical_binding is included.
    legacy_keys = [
        "family_id", "physical_case_id", "lineage_group_id", "mechanism_id",
        "geometry_family_id", "geometry", "control_family_id", "gravity_m_s2",
        "density_kg_m3", "parameters", "initial_state", "continuum_geometry",
    ]
    legacy = {key: copy.deepcopy(physical[key]) for key in legacy_keys if key in physical}
    legacy.update({
        "schema": "ds02.f1.fresh089.legacy-owner-metadata.v1",
        "case_id": case,
        "physical_condition_scope_schema": "legacy-owner-scope.v0",
        "canonical_owner": str(canonical_path),
        "canonical_owner_sha256": sha(canonical_path),
        "canonical_physical_condition_sha256": canonical["physical_condition_sha256"],
        "canonical_physical_binding_provenance": str(sidecar_path),
        "canonical_physical_binding_provenance_sha256": sha(sidecar_path),
        "strict_canonical_validation_granted": False,
        "strict_canonical_validation_reason": "physical_binding candidate_status/source_axis are retained in provenance sidecar; converter uses legacy-owner-scope.v0",
        "source_only": True,
        "execution_allowed": False,
        "launch_allowed": False,
        "mass_rescale": False,
        "q_n": "not_assessed",
        "production_approval": "none",
    })
    ensure("physical_binding" not in legacy, f"legacy owner accidentally contains explicit physical_binding: {case}")
    legacy_path = write_json(f"owners/{case}.legacy-owner-scope.v0.json", legacy)
    return legacy, legacy_path, sidecar_path


def legacy_scope_preflight(case: str, legacy_path: Path, sidecar_path: Path, canonical: dict) -> tuple[dict, str]:
    """Call the actual L/.venv scope helper on metadata only; never convert data."""
    code = (
        "import json,sys; "
        f"sys.path.insert(0,{str(INTEGRATION / 'lagrangian-fluid-lab/scripts')!r}); "
        "import ds_data02_direct_convert as c; "
        f"owner=json.load(open({str(legacy_path)!r}, encoding='utf-8')); "
        "print(json.dumps(c._physical_condition_scope(owner), sort_keys=True, separators=(',',':')))"
    )
    result = subprocess.run([str(PYTHON), "-c", code], check=True, capture_output=True, text=True)
    raw = result.stdout.strip().splitlines()[-1]
    scope = json.loads(raw)
    ensure(scope.get("schema") == "legacy-owner-scope.v0", f"legacy scope preflight schema mismatch: {case}")
    scope_hash = hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    preflight = {
        "schema": "ds02.f1.fresh089.legacy-scope-preflight.v1", "fresh_id": "fresh089", "case_id": case,
        "owner_metadata": str(legacy_path), "owner_metadata_sha256": sha(legacy_path),
        "canonical_provenance": str(sidecar_path), "canonical_provenance_sha256": sha(sidecar_path),
        "scope": scope, "scope_sha256": scope_hash,
        "scope_schema": "legacy-owner-scope.v0", "strict_canonical_validation_granted": False,
        "strict_canonical_validation_reason": "fresh088 explicit canonical binding was rejected by the unchanged allowlist; no fields were stripped from canonical provenance",
        "actual_converter_execution": False, "arrays_read": False, "jobs_launched": False,
        "status": "metadata_only_preflight_passed",
        "preflight_module": str(DIRECT_CONVERTER), "preflight_module_sha256": sha(DIRECT_CONVERTER),
        "approved_interpreter": str(PYTHON), "approved_interpreter_sha256": sha(PYTHON),
    }
    path = write_json(f"metadata/legacy-scope-preflight/{case}.json", preflight)
    return preflight, scope_hash


def adapter_for(case: str, upstream_owner: dict, canonical_path: Path, source_plan: Path, source_definition: Path, up_owner_path: Path, up_bind_path: Path, legacy_path: Path, legacy_scope_hash: str, sidecar_path: Path) -> tuple[dict, Path]:
    canonical = load(canonical_path)
    adapter = copy.deepcopy(upstream_owner)
    adapter.update({
        "schema": "ds02.f1.fresh089.actual-typed-xmf-owner-adapter.v1",
        "fresh_id": "fresh089",
        "canonical_owner": str(canonical_path),
        "canonical_owner_sha256": sha(canonical_path),
        "source_owner": str(canonical_path),
        "source_owner_sha256": sha(canonical_path),
        "source_definition": str(source_definition),
        "source_definition_sha256": sha(source_definition),
        "source_plan": str(source_plan),
        "source_plan_sha256": sha(source_plan),
        "upstream_fresh088_typed_owner": str(up_owner_path),
        "upstream_fresh088_typed_owner_sha256": sha(up_owner_path),
        "upstream_fresh088_binding": str(up_bind_path),
        "upstream_fresh088_binding_sha256": sha(up_bind_path),
        "converter_owner_metadata": str(legacy_path),
        "converter_owner_metadata_sha256": sha(legacy_path),
        "converter_legacy_scope_sha256": legacy_scope_hash,
        "converter_legacy_scope_schema": "legacy-owner-scope.v0",
        "canonical_physical_binding_provenance": str(sidecar_path),
        "canonical_physical_binding_provenance_sha256": sha(sidecar_path),
        "strict_canonical_validation_granted": False,
        "source_only": True,
        "execution_allowed": False,
        "launch_allowed": False,
        "typed_status": "future_root088_typed_conversion_then_fresh089_xmf",
        "xmf_ready_only_after_actual_typed_report_and_receipt": True,
        "legacy_scope_status": "deferred_until_actual_converter_report; never collapsed into canonical scope",
    })
    adapter_path = write_json(f"owners/{case}.typed-owner-xmf-adapter.json", adapter)
    return adapter, adapter_path


def actual_input_summary(bind: dict, owner: dict, request: dict) -> dict:
    actual_frame = bind["actual_native_frame0_qa"]
    actual_native = owner["actual_native"]
    qa = owner["actual_gencase_initial_qa"]
    counts = bind["actual_particle_counts"]
    return {
        "case_id": bind["case_id"],
        "genuine_source": "fresh088 Root283/Root298/Root299/Root307 evidence",
        "native_completed": owner["actual_native"].get("status") == "completed/0",
        "native_attempt_id": actual_native["attempt_id"],
        "native_receipt": actual_native["receipt"],
        "native_receipt_sha256": actual_native["receipt_sha256"],
        "actual_saved_frame_count": int(bind["actual_native_observed_frame_file_count"]),
        "actual_frame0_qa": {
            "attempt_id": actual_frame["attempt_id"],
            "status": actual_frame["status"],
            "passed": bool(actual_frame["passed"]),
            "actual_particle_counts": counts,
            "actual_total_particles": int(actual_frame["actual_total_particles"]),
            "native_rows": int(actual_frame["native_rows"]),
            "max_abs_velocity_error_m_per_s": actual_frame["max_abs_velocity_error_m_per_s"],
            "native_frame0_bi4_sha256": actual_frame["native_frame0_bi4_sha256"],
            "scientific_digest_source": "Root307 recorded report; not read or recomputed by fresh089 builder",
        },
        "actual_gencase_initial_qa": {
            "attempt_id": qa["attempt_id"],
            "status": qa["status"],
            "passed": bool(qa["passed"]),
            "receipt": qa["receipt"],
            "receipt_sha256": qa["receipt_sha256"],
            "report": qa["report"],
            "report_sha256": qa["report_sha256"],
        },
        "full_time_window_s": float(bind["full_time_window_s"]),
        "save_interval_s": float(bind["save_interval_s"]),
        "expected_dimension": 3,
        "typed_future_hashes_null": True,
        "raw_arrays_read": False,
    }


def dynamic_contract(bind: dict, owner: dict) -> dict:
    frame = bind["actual_native_frame0_qa"]
    counts = bind["actual_particle_counts"]
    return {
        "expected_dimension": 3,
        "frames": int(bind["expected_frames"]),
        "particles": int(bind["expected_particles"]),
        "actual_frame0_particle_counts": counts,
        "actual_frame0_total_particles": int(frame["actual_total_particles"]),
        "dynamic_shapes": {
            "position": ["frames", "particles", 3],
            "velocity": ["frames", "particles", 3],
            "valid": ["frames", "particles"],
            "particle_id": ["frames", "particles"],
            "particle_zone": ["frames", "particles"],
            "initial_type": ["frames", "particles"],
            "initial_mk": ["frames", "particles"],
            "initial_mass": ["frames", "particles"],
            "mass": ["frames", "particles"],
            "density": ["frames", "particles"],
            "pressure": ["frames", "particles"],
            "type": ["frames", "particles"],
        },
        "coordinate_semantics": "actual native XYZ positions; no camera crop or source coordinate rewrite",
        "velocity_semantics": "actual native XYZ velocity vectors; no source reshaping or inferred values",
        "mass_policy": "native mass weights; no continuum rescale",
        "native_fluid_type": 3,
        "native_fluid_mk": None,
        "native_fluid_mk_status": "not present in Root307 JSON metadata; Root converter/native decoder must verify actual Mk",
        "required_fields": ["valid", "initial_type", "particle_id", "particle_zone", "initial_mk", "initial_mass", "mass", "velocity", "density", "pressure", "type"],
    }



def typed_legacy_binding_and_request(case: str, bind: dict, owner: dict, request: dict, canonical: dict, canonical_path: Path, adapter_path: Path, legacy_path: Path, sidecar_path: Path, preflight: dict, legacy_scope_hash: str, source_plan: Path, source_definition: Path, up_bind_path: Path, up_owner_path: Path, up_req_path: Path) -> tuple[dict, Path, Path]:
    """Prepare a new disabled typed request using legacy-owner-scope.v0.

    fresh088's request/receipt bytes remain untouched under upstream/.  This
    sibling attempt is the only metadata correction: it points the unchanged
    converter at a metadata owner that passes its legacy fallback, while the
    full canonical physical binding remains an explicit provenance sidecar and
    strict canonical validation remains false.
    """
    slug = case.lower()
    frames = int(bind["expected_frames"])
    tmax = float(bind["full_time_window_s"])
    tout = float(bind["save_interval_s"])
    generated_xml = Path(bind["generated_xml"])
    generated_def = generated_xml.with_name(generated_xml.stem + "_Def.xml")
    attempt = f"root-stage1-f1-{slug}-full-native-typed-nvme-089-legacy-scope"
    output_root = DATA / case / attempt
    h5_path = output_root / "trajectory.h5"
    report_path = output_root / "conversion-report.json"
    receipt_path = output_root / "execution-receipt.json"
    binding_path = PACKAGE / "bindings/typed-legacy" / f"{case}.typed-nvme-binding.json"
    worker = CONVERTER
    # Only text/metadata and approved executable inputs are hashed here.
    paths = common_input_files(
        PYTHON, CONVERTER, DIRECT_CONVERTER, RUNTIME, STRICT, GOAL,
        ROOT230 / "launch.py", ROOT230 / "root_native_home_floor_inventory_policy.py", ROOT230 / "source-policy-contract.json",
        GPU_POLICY, RESOURCE, DECODER, PARTVTK,
        canonical_path, adapter_path, legacy_path, sidecar_path, source_plan, source_definition,
        PACKAGE / "metadata/root230-policy.json", PACKAGE / "metadata/legacy-scope-preflight" / f"{case}.json",
        up_bind_path, up_owner_path, up_req_path,
        Path(bind["generated_xml"]), generated_def,
        Path(bind["actual_gencase_receipt"]), Path(bind["actual_gencase_report"]),
        Path(owner["actual_gencase_initial_qa"]["request"]), Path(owner["actual_gencase_initial_qa"]["receipt"]), Path(owner["actual_gencase_initial_qa"]["report"]),
        Path(owner["actual_native"]["request"]), Path(owner["actual_native"]["receipt"]), Path(owner["actual_native"]["run_out"]),
        Path(bind["actual_native_frame0_qa"]["request"]), Path(bind["actual_native_frame0_qa"]["receipt"]), Path(bind["actual_native_frame0_qa"]["report"]),
    )
    input_files, input_sha = request_input_hashes(paths)
    root230 = load(PACKAGE / "metadata/root230-policy.json")["dispatch"]
    frame = bind["actual_native_frame0_qa"]
    native = owner["actual_native"]
    qa = owner["actual_gencase_initial_qa"]
    counts = bind["actual_particle_counts"]
    typed_binding = {
        "schema": "ds02.f1.fresh089.strict-legacy-typed-binding.v1", "family_id": "F1", "fresh_id": "fresh089", "case_id": case,
        "scope_id": "root_followup_089_f1_actual_typed_xmf_render_v1",
        "canonical_owner": str(canonical_path), "canonical_owner_sha256": sha(canonical_path),
        "source_owner": str(canonical_path), "source_owner_sha256": sha(canonical_path),
        "typed_owner": str(adapter_path), "typed_owner_sha256": sha(adapter_path),
        "legacy_owner_metadata": str(legacy_path), "legacy_owner_metadata_sha256": sha(legacy_path),
        "legacy_scope_preflight": str(PACKAGE / "metadata/legacy-scope-preflight" / f"{case}.json"),
        "legacy_scope_preflight_sha256": sha(PACKAGE / "metadata/legacy-scope-preflight" / f"{case}.json"),
        "legacy_h5_physical_condition_scope": {"schema": "legacy-owner-scope.v0", "physical_case_id": bind["physical_case_id"], "legacy_h5_physical_condition_sha256": legacy_scope_hash, "status": "expected_from_metadata_only_preflight; actual_converter_report_pending", "canonical_scope_is_separate": True},
        "legacy_h5_physical_condition_sha256": legacy_scope_hash,
        "canonical_physical_condition_sha256": bind["physical_condition_sha256"], "canonical_physical_binding_sha256": bind["canonical_physical_binding_sha256"],
        "canonical_physical_binding_provenance": str(sidecar_path), "canonical_physical_binding_provenance_sha256": sha(sidecar_path),
        "strict_canonical_validation_granted": False,
        "strict_canonical_validation_reason": "fresh088 canonical physical_binding rejected by unchanged allowlist for candidate_status/source_axis; no stripping or reclassification",
        "physical_case_id": bind["physical_case_id"], "topphysical_case_id": bind["physical_case_id"],
        "source_plan_condition_sha256": bind.get("source_plan_condition_sha256"),
        "source_definition": str(source_definition), "source_definition_sha256": sha(source_definition),
        "generated_def": str(generated_def), "generated_def_sha256": sha(generated_def),
        "generated_xml": str(generated_xml), "generated_xml_sha256": bind["generated_xml_sha256"],
        "actual_gencase_receipt": bind["actual_gencase_receipt"], "actual_gencase_receipt_sha256": bind["actual_gencase_receipt_sha256"],
        "actual_gencase_report": bind["actual_gencase_report"], "actual_gencase_report_sha256": bind["actual_gencase_report_sha256"],
        "actual_gencase_initial_qa": {"attempt_id": qa["attempt_id"], "request": qa["request"], "request_sha256": qa["request_sha256"], "receipt": qa["receipt"], "receipt_sha256": qa["receipt_sha256"], "report": qa["report"], "report_sha256": qa["report_sha256"], "status": "completed/0", "passed": True},
        "actual_native_receipt": native["receipt"], "actual_native_receipt_sha256": native["receipt_sha256"], "actual_native_request": native["request"], "actual_native_request_sha256": native["request_sha256"], "actual_native_run_out": native["run_out"], "actual_native_run_out_sha256": native["run_out_sha256"], "actual_native_attempt_id": native["attempt_id"], "actual_native_expected_frames": frames, "actual_native_observed_frame_file_count": int(bind["actual_native_observed_frame_file_count"]),
        "actual_frame0_qa": {"request": frame["request"], "request_sha256": frame["request_sha256"], "receipt": frame["receipt"], "receipt_sha256": frame["receipt_sha256"], "report": frame["report"], "report_sha256": frame["report_sha256"], "attempt_id": frame["attempt_id"], "status": "completed/0", "passed": True, "actual_particle_counts": counts, "actual_total_particles": int(frame["actual_total_particles"]), "native_rows": int(frame["native_rows"]), "native_frame0_bi4_sha256": frame["native_frame0_bi4_sha256"], "max_abs_velocity_error_m_per_s": frame["max_abs_velocity_error_m_per_s"]},
        "typed_output_root": str(output_root), "typed_output_h5": str(h5_path), "typed_output_sha256": None,
        "typed_conversion_report": str(report_path), "typed_conversion_report_sha256": None,
        "typed_execution_receipt": str(receipt_path), "typed_execution_receipt_sha256": None,
        "expected_frames": frames, "expected_particles": int(bind["expected_particles"]), "expected_dimension": 3, "full_time_window_s": tmax, "save_interval_s": tout,
        "actual_particle_counts": counts, "max_abs_velocity_error_m_per_s": frame["max_abs_velocity_error_m_per_s"],
        "typed_status": "source_only_disabled_waiting_actual_legacy_scope_typed_conversion", "future_hashes_null": True,
        "raw_arrays_read": False, "mass_rescale": False, "independent_case_count_increment": 0, "q_n": "not_assessed", "production_approval": "none",
        "source_only": True, "execution_allowed": False, "launch_allowed": False, "root_review_required": True,
        "input_files": input_files, "input_sha256": input_sha,
        "root230_dispatch": root230, "nvme_policy": request["nvme_policy"] if isinstance(request, dict) and "nvme_policy" in request else load(up_req_path)["nvme_policy"],
        "parent_budget": load(up_req_path)["parent_budget"], "physical_recipe_unchanged": True,
        "upstream_fresh088_binding": str(up_bind_path), "upstream_fresh088_binding_sha256": sha(up_bind_path),
        "upstream_fresh088_owner": str(up_owner_path), "upstream_fresh088_owner_sha256": sha(up_owner_path),
        "upstream_fresh088_request": str(up_req_path), "upstream_fresh088_request_sha256": sha(up_req_path),
        "status": "source_only_disabled_new_attempt_after_fresh088_canonical_scope_preflight_failure",
    }
    # The source request has no self-reference in its binding hash closure.
    binding_path.parent.mkdir(parents=True, exist_ok=True)
    binding_path.write_text(json.dumps(typed_binding, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    command = [
        str(PYTHON), str(CONVERTER), "--staging-root", "/tmp/ds02-nvme-conversion", "--staging-limit-bytes", "25769803776", "--",
        "--data-root", native["data_root"], "--generated-xml", str(generated_xml), "--output", "{attempt_root}/trajectory.h5", "--report", "{attempt_root}/conversion-report.json",
        "--solver-log", native["run_out"], "--solver-receipt", native["receipt"], "--gencase-receipt", bind["actual_gencase_receipt"],
        "--decoder", str(DECODER), "--partvtk", str(PARTVTK), "--validation-dir", "{attempt_root}/partvtk-validation", "--keep-validation-csv",
        "--owner-metadata", str(legacy_path), "--particle-chunk", "65536",
    ]
    typed_request = {
        "schema": "ds02.runner-request.v2", "fresh_id": "fresh089", "family_id": "F1", "case_id": case, "scope_id": "root_followup_089_f1_actual_typed_xmf_render_v1",
        "kind": "cpu", "cpu_task_kind": "conversion", "cpu_threads": 2, "attempt_id": attempt,
        "cwd": str(INTEGRATION / "lagrangian-fluid-lab"), "worktree_root": str(F1), "command": command,
        "binding": str(binding_path), "binding_sha256": sha(binding_path),
        "actual_gencase_initial_qa": typed_binding["actual_gencase_initial_qa"],
        "actual_native_receipt": native["receipt"], "actual_native_receipt_sha256": native["receipt_sha256"],
        "actual_native_frame0_qa": typed_binding["actual_frame0_qa"],
        "depends_on_attempts": [qa["attempt_id"], native["attempt_id"], frame["attempt_id"]],
        "depends_on": "Root298 GenQA completed/0 -> Root299 native completed/0 -> Root307 frame0 QA completed/0 -> strict legacy-scope preflight passed",
        "disabled": True, "launch": False, "execution_allowed": False, "launch_allowed": False, "source_only": True, "root_review_required": True, "launch_owner": "root",
        "status": "source_only_disabled_waiting_root_review_and_actual_conversion", "production_approval": "none", "q_n": "not_assessed", "independent_case_count_increment": 0,
        "estimated_storage_bytes": 25769803776, "max_wall_seconds": 14400,
        "future_input_files": [native["data_root"], str(Path(native["data_root"]) / "Part_0000.bi4")], "future_input_sha256": None,
        "future_outputs": {"attempt_root": str(output_root), "trajectory_h5": str(h5_path), "conversion_report": str(report_path), "execution_receipt": str(receipt_path), "trajectory_h5_sha256": None, "conversion_report_sha256": None, "execution_receipt_sha256": None, "typed_partvtk_sha256": None, "typed_partvtk_validation": "{attempt_root}/partvtk-validation/*.csv"},
        "input_files": input_files + [str(binding_path)], "input_sha256": {**input_sha, str(binding_path): sha(binding_path)},
        "nvme_policy": load(up_req_path)["nvme_policy"], "root230_dispatch": root230, "parent_budget": load(up_req_path)["parent_budget"],
        "canonical_condition": {"physical_case_id": bind["physical_case_id"], "physical_condition_sha256": bind["physical_condition_sha256"], "canonical_physical_binding_sha256": bind["canonical_physical_binding_sha256"], "source_plan_condition_sha256": bind.get("source_plan_condition_sha256")},
        "legacy_h5_physical_condition_scope": typed_binding["legacy_h5_physical_condition_scope"], "legacy_owner_metadata": str(legacy_path), "legacy_owner_metadata_sha256": sha(legacy_path), "legacy_scope_preflight": typed_binding["legacy_scope_preflight"], "legacy_scope_preflight_sha256": typed_binding["legacy_scope_preflight_sha256"],
        "strict_canonical_validation_granted": False, "canonical_physical_binding_provenance": str(sidecar_path), "canonical_physical_binding_provenance_sha256": sha(sidecar_path),
        "typed_field_contract": {"full_native_frames": frames, "full_time_window_s": tmax, "output_timestep_s": tout, "actual_native_particle_counts": counts, "actual_native_rows": int(frame["native_rows"]), "actual_native_dimension": 3, "max_abs_velocity_error_m_per_s": frame["max_abs_velocity_error_m_per_s"], "required_fields": ["Idp", "Zone", "Type", "Mk", "position", "velocity", "density", "mass", "pressure"], "preserve_native_identity": "UID/Zone/Type/Mk and native mass; no rescale", "q_n": "not_assessed"},
        "raw_arrays_read": False, "mass_rescale": False, "physical_recipe_unchanged": True,
    }
    typed_request_path = write_json(f"requests/typed-legacy/{case}.full-native-typed-nvme-legacy.request.json", typed_request)
    return typed_binding, binding_path, typed_request_path

def xmf_binding(case: str, bind: dict, owner: dict, request: dict, canonical: dict, canonical_path: Path, adapter_path: Path, source_plan: Path, source_definition: Path, up_bind_path: Path, up_req_path: Path, up_owner_path: Path, typed_bind: dict, typed_bind_path: Path, typed_req_path: Path, legacy_path: Path, sidecar_path: Path, preflight: dict, legacy_scope_hash: str) -> tuple[dict, Path]:
    slug = case.lower()
    frames = int(bind["expected_frames"])
    full_window = float(bind["full_time_window_s"])
    generated_xml = Path(bind["generated_xml"])
    generated_def = generated_xml.with_name(generated_xml.stem + "_Def.xml")
    typed_root = Path(typed_bind["typed_output_root"])
    xmf_base = DATA / case / f"root-stage1-f1-{slug}-full{frames}-paraview-dynamic-xdmf-089"
    xmf_dir = xmf_base / "xdmf"
    render_base = DATA / case / f"root-stage1-f1-{slug}-full{frames}-native023-render-089"
    render_dir = render_base / "render"
    frame = bind["actual_native_frame0_qa"]
    native = owner["actual_native"]
    qa = owner["actual_gencase_initial_qa"]
    canonical_sha = sha(canonical_path)
    source_def_sha = sha(source_definition)
    bind_value = {
        "schema": "ds02.f1.fresh089.legacy-aware-temporal-binding.v1",
        "scope_id": "root_followup_089_f1_actual_typed_xmf_render_v1",
        "fresh_id": "fresh089", "family_id": "F1", "case_id": case,
        "canonical_owner": str(canonical_path), "canonical_owner_sha256": canonical_sha,
        "typed_owner": str(adapter_path), "typed_owner_sha256": sha(adapter_path),
        "upstream_fresh088_binding": str(up_bind_path), "upstream_fresh088_binding_sha256": sha(up_bind_path),
        "upstream_fresh088_typed_owner": str(up_owner_path), "upstream_fresh088_typed_owner_sha256": sha(up_owner_path),
        "upstream_fresh088_typed_request": str(up_req_path), "upstream_fresh088_typed_request_sha256": sha(up_req_path),
        "fresh089_typed_binding": str(typed_bind_path), "fresh089_typed_binding_sha256": sha(typed_bind_path),
        "fresh089_typed_request": str(typed_req_path), "fresh089_typed_request_sha256": sha(typed_req_path),
        "legacy_owner_metadata": str(legacy_path), "legacy_owner_metadata_sha256": sha(legacy_path),
        "legacy_scope_preflight": str(preflight.get("_path", PACKAGE / "metadata/legacy-scope-preflight" / f"{case}.json")), "legacy_scope_preflight_sha256": sha(Path(preflight.get("_path", PACKAGE / "metadata/legacy-scope-preflight" / f"{case}.json"))),
        "canonical_physical_binding_provenance": str(sidecar_path), "canonical_physical_binding_provenance_sha256": sha(sidecar_path),
        "strict_canonical_validation_granted": False,
        "canonical_physical_condition_sha256": canonical["physical_condition_sha256"],
        "canonical_physical_binding_sha256": bind["canonical_physical_binding_sha256"],
        "physical_case_id": bind["physical_case_id"], "topphysical_case_id": bind["physical_case_id"],
        "source_plan_condition_sha256": bind.get("source_plan_condition_sha256"),
        "source_definition": str(source_definition), "source_definition_sha256": source_def_sha,
        "generated_def": str(generated_def), "generated_def_sha256": sha(generated_def),
        "generated_xml": str(generated_xml), "generated_xml_sha256": bind["generated_xml_sha256"],
        "actual_gencase_receipt": bind["actual_gencase_receipt"], "actual_gencase_receipt_sha256": bind["actual_gencase_receipt_sha256"],
        "actual_gencase_report": bind["actual_gencase_report"], "actual_gencase_report_sha256": bind["actual_gencase_report_sha256"],
        "actual_gencase_initial_qa": {
            "request": qa["request"], "request_sha256": qa["request_sha256"],
            "receipt": qa["receipt"], "receipt_sha256": qa["receipt_sha256"],
            "report": qa["report"], "report_sha256": qa["report_sha256"],
            "status": "completed/0", "passed": True,
        },
        "actual_native_receipt": native["receipt"], "actual_native_receipt_sha256": native["receipt_sha256"],
        "actual_native_request": native["request"], "actual_native_request_sha256": native["request_sha256"],
        "actual_native_run_out": native["run_out"], "actual_native_run_out_sha256": native["run_out_sha256"],
        "actual_native_attempt_id": native["attempt_id"], "actual_native_observed_frame_file_count": int(bind["actual_native_observed_frame_file_count"]),
        "actual_frame0_qa": {
            "request": frame["request"], "request_sha256": frame["request_sha256"],
            "receipt": frame["receipt"], "receipt_sha256": frame["receipt_sha256"],
            "report": frame["report"], "report_sha256": frame["report_sha256"],
            "attempt_id": frame["attempt_id"], "status": "completed/0", "passed": True,
            "actual_particle_counts": frame["actual_particle_counts"], "actual_total_particles": frame["actual_total_particles"],
            "native_rows": frame["native_rows"], "max_abs_velocity_error_m_per_s": frame["max_abs_velocity_error_m_per_s"],
            "native_frame0_bi4_sha256": frame["native_frame0_bi4_sha256"],
            "scientific_digest_source": "Root307 recorded evidence; fresh089 does not read/recompute BI4",
        },
        "typed_conversion_report": typed_bind["typed_conversion_report"], "typed_conversion_report_sha256": None,
        "typed_execution_receipt": typed_bind["typed_execution_receipt"], "typed_execution_receipt_sha256": None,
        "typed_output_h5": typed_bind["typed_output_h5"], "typed_output_sha256": None,
        "typed_status": "pending_actual_fresh089_legacy_scope_typed_conversion",
        "legacy_h5_physical_condition_scope": typed_bind["legacy_h5_physical_condition_scope"],
        "legacy_h5_physical_condition_sha256": legacy_scope_hash,
        "expected_frames": frames, "expected_particles": int(bind["expected_particles"]), "expected_dimension": 3,
        "physical_window_s": [0.0, full_window], "save_interval_s": float(bind["save_interval_s"]),
        "dynamic_native_shape_contract": dynamic_contract(bind, owner),
        "native_identity_contract": {
            "required_fields": ["valid", "initial_type", "particle_id", "particle_zone", "initial_mk", "initial_mass", "mass", "velocity", "density", "pressure", "type"],
            "native_fluid_type": 3, "native_fluid_mk": None,
            "native_fluid_mk_status": "deferred to actual Root typed decoder; not fabricated",
            "mass_policy": "native mass weights; no continuum rescale",
            "expected_dimension": 3,
            "dynamic_shapes": dynamic_contract(bind, owner)["dynamic_shapes"],
        },
        "owner_scopes": {
            "canonical": {"schema": "ds-data-02.physical-binding.v1", "physical_condition_sha256": canonical["physical_condition_sha256"], "sha256": canonical["physical_condition_sha256"], "owner": str(canonical_path)},
            "source": {"owner": str(canonical_path), "owner_sha256": canonical_sha, "source_plan_condition_sha256": bind.get("source_plan_condition_sha256")},
            "typed_adapter": {"owner": str(adapter_path), "owner_sha256": sha(adapter_path), "status": "adapter only; actual converter receipt pending"},
            "legacy_h5": {"schema": "legacy-owner-scope.v0", "owner_metadata": str(legacy_path), "owner_metadata_sha256": sha(legacy_path), "physical_condition_sha256": legacy_scope_hash, "status": "expected_from_metadata_only_preflight; actual converter report pending"},
        },
        "root193_xmf": {
            "attempt_id": f"root-stage1-f1-{slug}-full{frames}-paraview-dynamic-xdmf-089",
            "attempt_root": str(xmf_base), "output_dir": str(xmf_dir),
            "execution_receipt": str(xmf_base / "execution-receipt.json"),
            "manifest": str(xmf_dir / "manifest.json"), "xdmf": str(xmf_dir / "case.xmf"),
            "execution_receipt_sha256": None, "manifest_sha256": None, "xdmf_sha256": None,
        },
        "root194_render": {
            "attempt_id": f"root-stage1-f1-{slug}-full{frames}-native023-render-089",
            "attempt_root": str(render_base), "output_dir": str(render_dir),
            "execution_receipt": str(render_base / "execution-receipt.json"),
            "report": str(render_dir / "paraview-full-animation-report.json"),
            "frame_sha256": None, "report_sha256": None, "execution_receipt_sha256": None,
        },
        "legacy_canonical_mapping": {
            "canonical_hash_is_physical_binding_json": True,
            "legacy_hash_is_converter_report_and_h5_attribute": True,
            "legacy_scope_schema": "legacy-owner-scope.v0",
            "cross_resolution_precision_claim": False,
        },
        "camera_bounds_policy": "native023 scans valid native positions across every actual saved XDMF time; no fixed camera/domain bounds",
        "full_saved_frames_required": True,
        "independent_case_count_increment": 0, "production_approval": "none", "q_n": "not_assessed",
        "source_only": True, "execution_allowed": False, "launch_allowed": False, "root_review_required": True,
        "future_hashes_null": True,
        "raw_arrays_read": False,
        "status": "source_only_disabled_waiting_actual_legacy_scope_typed_report_then_xmf",
    }
    return bind_value, write_json(f"bindings/xmf/{case}.legacy-aware-binding.json", bind_value)


def common_input_files(*paths: Path) -> list[Path]:
    return unique_paths([Path(p) for p in paths])


def request_input_hashes(paths: list[Path]) -> tuple[list[str], dict[str, str]]:
    safe = []
    for path in unique_paths(paths):
        safe_external(path, "request input")
        safe.append(str(path))
    return sorted(safe), {str(p): sha(p) for p in sorted(unique_paths(paths), key=str)}


def xmf_request(case: str, bind: dict, xmf_bind: dict, xmf_path: Path, typed_req_path: Path, typed_bind_path: Path, up_owner_path: Path, up_bind_path: Path, up_req_path: Path, source_plan: Path, source_definition: Path, canonical_path: Path, adapter_path: Path, legacy_path: Path, sidecar_path: Path) -> Path:
    slug = case.lower(); frames = int(bind["expected_frames"])
    worker = PACKAGE / "workers/export_xmf_legacy_aware.py"
    frame = bind["actual_native_frame0_qa"]
    native = xmf_bind["actual_native_request"]
    owner = load(up_owner_path)
    paths = common_input_files(
        PYTHON, RUNTIME, STRICT, GOAL, ROOT230 / "launch.py", ROOT230 / "root_native_home_floor_inventory_policy.py", ROOT230 / "source-policy-contract.json",
        GPU_POLICY, RESOURCE, CONVERTER, DIRECT_CONVERTER, DECODER, PARTVTK,
        worker, xmf_path, typed_req_path, typed_bind_path, up_bind_path, up_owner_path, up_req_path,
        legacy_path, sidecar_path, PACKAGE / "metadata/legacy-scope-preflight" / f"{case}.json",
        PACKAGE / "metadata/root230-policy.json", canonical_path, adapter_path, source_plan, source_definition,
        Path(xmf_bind["generated_xml"]), Path(xmf_bind["generated_def"]), Path(xmf_bind["actual_gencase_receipt"]), Path(xmf_bind["actual_gencase_report"]),
        Path(xmf_bind["actual_gencase_initial_qa"]["request"]), Path(xmf_bind["actual_gencase_initial_qa"]["receipt"]), Path(xmf_bind["actual_gencase_initial_qa"]["report"]),
        Path(native), Path(xmf_bind["actual_native_receipt"]), Path(xmf_bind["actual_native_run_out"]),
        Path(frame["request"]), Path(frame["receipt"]), Path(frame["report"]),
    )
    input_files, input_sha = request_input_hashes(paths)
    root230 = load(PACKAGE / "metadata/root230-policy.json")["dispatch"]
    typed_req = load(typed_req_path)
    attempt = xmf_bind["root193_xmf"]["attempt_id"]
    request = {
        "schema": "ds02.runner-request.v2", "fresh_id": "fresh089", "family_id": "F1", "case_id": case,
        "scope_id": "root_followup_089_f1_actual_typed_xmf_render_v1", "kind": "cpu", "cpu_task_kind": "conversion", "cpu_threads": 2,
        "attempt_id": attempt, "cwd": str(INTEGRATION / "lagrangian-fluid-lab"), "worktree_root": str(F1),
        "command": [str(PYTHON), str(worker), "--binding", str(xmf_path), "--output-dir", "{attempt_root}/xdmf"],
        "binding": str(xmf_path), "binding_sha256": sha(xmf_path),
        "depends_on_attempts": [
            typed_req["actual_gencase_initial_qa"]["attempt_id"],
            typed_req["actual_native_receipt"].split("/")[-2] if "/" in typed_req["actual_native_receipt"] else typed_req["attempt_id"],
            typed_req["actual_native_frame0_qa"]["attempt_id"], typed_req["attempt_id"],
        ],
        "depends_on": "Root298 GenQA completed/0 -> Root299 native completed/0 -> Root307 frame0 QA completed/0 -> fresh089 legacy-scope typed conversion completed/0",
        "disabled": True, "launch": False, "execution_allowed": False, "launch_allowed": False, "source_only": True, "root_review_required": True, "launch_owner": "root",
        "status": "source_only_disabled_waiting_actual_typed_conversion", "production_approval": "none", "q_n": "not_assessed", "independent_case_count_increment": 0,
        "estimated_storage_bytes": 8589934592, "max_wall_seconds": 1800,
        "future_input_files": [xmf_bind["typed_output_h5"], xmf_bind["typed_conversion_report"], xmf_bind["typed_execution_receipt"]], "future_input_sha256": None,
        "future_outputs": xmf_bind["root193_xmf"],
        "input_files": input_files, "input_sha256": input_sha,
        "root230_dispatch": root230,
        "nvme_policy": typed_req["nvme_policy"],
        "parent_budget": typed_req["parent_budget"], "physical_recipe_unchanged": True,
        "typed_owner": str(adapter_path), "typed_owner_sha256": sha(adapter_path),
        "typed_binding": str(typed_bind_path), "typed_binding_sha256": sha(typed_bind_path),
        "legacy_owner_metadata": str(legacy_path), "legacy_owner_metadata_sha256": sha(legacy_path),
        "source_owner": str(canonical_path), "source_owner_sha256": sha(canonical_path),
        "canonical_condition": {"physical_case_id": bind["physical_case_id"], "physical_condition_sha256": bind["physical_condition_sha256"], "canonical_physical_binding_sha256": bind["canonical_physical_binding_sha256"], "source_plan_condition_sha256": bind.get("source_plan_condition_sha256")},
        "legacy_h5_physical_condition_scope": xmf_bind["legacy_h5_physical_condition_scope"],
        "dynamic_native_shape_contract": xmf_bind["dynamic_native_shape_contract"],
        "raw_arrays_read": False, "mass_rescale": False, "physical_condition_scope": "canonical/source owner scope and deferred legacy H5 scope remain distinct; no precision/Q-N claim",
    }
    return write_json(f"requests/xmf/{case}.root193-xmf.request.json", request)


def render_binding(case: str, bind: dict, xmf_bind: dict, xmf_path: Path, canonical_path: Path, adapter_path: Path) -> tuple[dict, Path]:
    frames = int(bind["expected_frames"])
    rb = {
        "schema": "ds02.f1.fresh089.native023-render-binding.v1", "family_id": "F1", "fresh_id": "fresh089", "case_id": case,
        "canonical_owner": str(canonical_path), "canonical_owner_sha256": sha(canonical_path),
        "typed_owner": str(adapter_path), "typed_owner_sha256": sha(adapter_path),
        "canonical_physical_condition_sha256": bind["physical_condition_sha256"], "canonical_physical_binding_sha256": bind["canonical_physical_binding_sha256"],
        "physical_case_id": bind["physical_case_id"], "topphysical_case_id": bind["physical_case_id"],
        "xmf_binding": str(xmf_path), "xmf_binding_sha256": sha(xmf_path),
        "xmf_manifest": xmf_bind["root193_xmf"]["manifest"], "xmf_manifest_sha256": None,
        "xdmf": xmf_bind["root193_xmf"]["xdmf"], "xdmf_sha256": None,
        "typed_output_h5": xmf_bind["typed_output_h5"], "typed_output_sha256": None,
        "expected_frames": frames, "expected_particles": int(bind["expected_particles"]), "expected_dimension": 3,
        "native_identity_contract": xmf_bind["native_identity_contract"],
        "dynamic_native_shape_contract": xmf_bind["dynamic_native_shape_contract"],
        "camera_bounds_policy": "native023 auto-all-frame native bounds; no source camera crop",
        "full_saved_frames_required": True,
        "visual_status": "pending actual Root023 software full-animation render",
        "precision_status": "not accepted; no Q-N claim",
        "future_outputs": xmf_bind["root194_render"],
        "root_review_required": True, "source_only": True, "execution_allowed": False, "launch_allowed": False,
        "production_approval": "none", "q_n": "not_assessed", "independent_case_count_increment": 0,
        "status": "source_only_disabled_waiting_root_xmf_manifest", "future_hashes_null": True,
        "raw_arrays_read": False,
    }
    return rb, write_json(f"bindings/render/{case}.native023-render-binding.json", rb)


def render_request(case: str, bind: dict, xmf_bind: dict, rb: dict, render_path: Path, xmf_path: Path, xmf_req_path: Path, canonical_path: Path, adapter_path: Path, source_plan: Path, source_definition: Path) -> Path:
    frames = int(bind["expected_frames"]); slug = case.lower(); worker = PACKAGE / "workers/render_native023.py"
    paths = common_input_files(
        RUNTIME, STRICT, GOAL, ROOT230 / "launch.py", ROOT230 / "root_native_home_floor_inventory_policy.py", ROOT230 / "source-policy-contract.json", GPU_POLICY, RESOURCE,
        worker, PVPYTHON, render_path, xmf_path, xmf_req_path, PACKAGE / "metadata/root230-policy.json", canonical_path, adapter_path, source_plan, source_definition,
        Path(xmf_bind["generated_xml"]), Path(xmf_bind["generated_def"]), Path(xmf_bind["actual_gencase_receipt"]), Path(xmf_bind["actual_gencase_report"]),
        Path(xmf_bind["actual_gencase_initial_qa"]["receipt"]), Path(xmf_bind["actual_gencase_initial_qa"]["report"]), Path(xmf_bind["actual_native_receipt"]), Path(xmf_bind["actual_native_run_out"]), Path(xmf_bind["actual_frame0_qa"]["receipt"]), Path(xmf_bind["actual_frame0_qa"]["report"]),
    )
    input_files, input_sha = request_input_hashes(paths)
    env = [
        "/usr/bin/env", "VTK_SMP_MAX_THREADS=2", "LP_NUM_THREADS=2", "LIBGL_ALWAYS_SOFTWARE=1",
        "MESA_LOADER_DRIVER_OVERRIDE=llvmpipe", "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json",
        "VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow", "QT_QPA_PLATFORM=offscreen", "OMP_NUM_THREADS=2",
    ]
    command = env + [str(PVPYTHON), "--force-offscreen-rendering", str(worker), "--manifest", xmf_bind["root193_xmf"]["manifest"], "--output-dir", "{attempt_root}/render"]
    root230 = load(PACKAGE / "metadata/root230-policy.json")["dispatch"]
    request = {
        "schema": "ds02.runner-request.v2", "fresh_id": "fresh089", "family_id": "F1", "case_id": case,
        "scope_id": "root_followup_089_f1_actual_typed_xmf_render_v1", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2,
        "attempt_id": xmf_bind["root194_render"]["attempt_id"], "cwd": str(INTEGRATION / "lagrangian-fluid-lab"), "worktree_root": str(F1),
        "command": command, "binding": str(render_path), "binding_sha256": sha(render_path),
        "depends_on_attempts": [xmf_bind["root193_xmf"]["attempt_id"], load(xmf_req_path)["attempt_id"]],
        "depends_on": "fresh089 XMF completed/0 with actual manifest, then Root023 software full-animation render",
        "disabled": True, "launch": False, "execution_allowed": False, "launch_allowed": False, "source_only": True, "root_review_required": True, "launch_owner": "root",
        "status": "source_only_disabled_waiting_root_xmf_manifest", "production_approval": "none", "q_n": "not_assessed", "independent_case_count_increment": 0,
        "estimated_storage_bytes": 8589934592, "max_wall_seconds": 1800,
        "future_input_files": [xmf_bind["root193_xmf"]["manifest"], xmf_bind["root193_xmf"]["xdmf"], xmf_bind["typed_output_h5"]], "future_input_sha256": None,
        "future_outputs": rb["future_outputs"], "input_files": input_files, "input_sha256": input_sha,
        "root230_dispatch": root230, "parent_budget": "Root resource window 512 GPUh / 3840 CPUcoreh / qualification1024 / production720; no reservation in source turn",
        "camera_bounds_policy": "native023 auto-all-frame native bounds", "dynamic_native_shape_contract": rb["dynamic_native_shape_contract"],
        "typed_owner": str(adapter_path), "typed_owner_sha256": sha(adapter_path), "source_owner": str(canonical_path), "source_owner_sha256": sha(canonical_path),
        "canonical_condition": {"physical_case_id": bind["physical_case_id"], "physical_condition_sha256": bind["physical_condition_sha256"], "canonical_physical_binding_sha256": bind["canonical_physical_binding_sha256"]},
        "software_only_cpu_renderer": True, "raw_arrays_read": False, "physical_recipe_unchanged": True,
    }
    return write_json(f"requests/render/{case}.root194-render.request.json", request)


def build() -> None:
    PACKAGE.mkdir(parents=True, exist_ok=True)
    for path in [FRESH088, OLD087, ROOT230, GPU_POLICY, RESOURCE, RUNTIME, STRICT, GOAL, PYTHON, CONVERTER, DIRECT_CONVERTER, DECODER, PARTVTK, PVPYTHON, VALIDATOR]:
        ensure(Path(path).exists(), f"required path missing: {path}")
    for directory in ["metadata", "metadata/contracts", "metadata/producer", "metadata/legacy-scope-preflight", "source/owners", "source/definitions", "source/source-plans", "source/gencase-bindings", "upstream/fresh088", "owners", "provenance", "bindings/typed-legacy", "bindings/xmf", "bindings/render", "requests/typed-legacy", "requests/xmf", "requests/render", "workers"]:
        (PACKAGE / directory).mkdir(parents=True, exist_ok=True)
    copy_upstream()
    root230_meta = load(FRESH088 / "metadata/root230-policy.json")
    root230_meta.update({"schema": "ds02.f1.fresh089.root230-policy-binding.v1", "fresh_id": "fresh089", "source_only": True, "disabled": True, "launch_allowed": False, "root_solver_concurrency_cap": 8, "downstream_only": True})
    write_json("metadata/root230-policy.json", root230_meta)
    write_json("metadata/contracts/xmf-contract.json", {
        "schema": "ds02.f1.fresh089.xmf-contract.v1", "worker": "workers/export_xmf_legacy_aware.py",
        "requires_actual_typed_report_receipt_and_h5": True, "requires_actual_legacy_owner_scope": True,
        "canonical_scope_is_separate": True, "frames_and_particles": "dynamic actual converter report, never source rounded count",
        "fields": ["time", "position XYZ", "valid", "initial_type", "particle_id", "particle_zone", "initial_mk", "initial_mass", "mass", "velocity XYZ", "density", "pressure", "type"],
        "status": "source_only_disabled",
    })
    write_json("metadata/contracts/root023-render-contract.json", {
        "schema": "ds02.f1.fresh089.root023-render-contract.v1", "worker": "workers/render_native023.py",
        "software_only": True, "all_actual_saved_frames": True, "camera_bounds": "native023 auto-all-frame native bounds",
        "output_child_directory": "render", "status": "source_only_disabled",
    })
    rows = []
    for case in CASES:
        bind, up_owner, up_req, canonical, _gencase, canonical_path, source_plan, source_definition = load_case(case)
        up_bind_path = PACKAGE / "upstream/fresh088/bindings" / f"{case}.typed-nvme-binding.json"
        up_owner_path = PACKAGE / "upstream/fresh088/owners" / f"{case}.typed-owner.json"
        up_req_path = PACKAGE / "upstream/fresh088/requests" / f"{case}.full-native-typed-nvme.request.json"
        legacy_owner, legacy_path, sidecar_path = legacy_owner_for(case, canonical, canonical_path)
        preflight, legacy_scope_hash = legacy_scope_preflight(case, legacy_path, sidecar_path, canonical)
        adapter, adapter_path = adapter_for(case, up_owner, canonical_path, source_plan, source_definition, up_owner_path, up_bind_path, legacy_path, legacy_scope_hash, sidecar_path)
        typed_bind, typed_bind_path, typed_req_path = typed_legacy_binding_and_request(case, bind, up_owner, up_req, canonical, canonical_path, adapter_path, legacy_path, sidecar_path, preflight, legacy_scope_hash, source_plan, source_definition, up_bind_path, up_owner_path, up_req_path)
        xmf_bind, xmf_path = xmf_binding(case, bind, up_owner, up_req, canonical, canonical_path, adapter_path, source_plan, source_definition, up_bind_path, up_req_path, up_owner_path, typed_bind, typed_bind_path, typed_req_path, legacy_path, sidecar_path, preflight, legacy_scope_hash)
        xmf_req_path = xmf_request(case, bind, xmf_bind, xmf_path, typed_req_path, typed_bind_path, up_owner_path, up_bind_path, up_req_path, source_plan, source_definition, canonical_path, adapter_path, legacy_path, sidecar_path)
        render_bind, render_path = render_binding(case, bind, xmf_bind, xmf_path, canonical_path, adapter_path)
        render_req_path = render_request(case, bind, xmf_bind, render_bind, render_path, xmf_path, xmf_req_path, canonical_path, adapter_path, source_plan, source_definition)
        summary = actual_input_summary(bind, up_owner, up_req)
        summary.update({
            "upstream_binding": str(up_bind_path), "upstream_binding_sha256": sha(up_bind_path),
            "upstream_typed_owner": str(up_owner_path), "upstream_typed_owner_sha256": sha(up_owner_path),
            "upstream_typed_request": str(up_req_path), "upstream_typed_request_sha256": sha(up_req_path),
            "canonical_owner": str(canonical_path), "canonical_owner_sha256": sha(canonical_path),
            "adapter_owner": str(adapter_path), "adapter_owner_sha256": sha(adapter_path),
            "legacy_owner_metadata": str(legacy_path), "legacy_owner_metadata_sha256": sha(legacy_path),
            "legacy_scope_preflight": str(PACKAGE / "metadata/legacy-scope-preflight" / f"{case}.json"), "legacy_scope_sha256": legacy_scope_hash,
            "canonical_physical_binding_provenance": str(sidecar_path), "canonical_physical_binding_provenance_sha256": sha(sidecar_path),
            "strict_canonical_validation_granted": False,
            "fresh089_typed_binding": str(typed_bind_path), "fresh089_typed_request": str(typed_req_path),
            "xmf_binding": str(xmf_path), "xmf_request": str(xmf_req_path), "render_binding": str(render_path), "render_request": str(render_req_path),
            "typed_status": "future Root conversion with strict legacy-owner scope; hashes null", "xmf_status": "disabled future", "render_status": "disabled future",
        })
        write_json(f"metadata/producer/{case}.json", summary)
        rows.append(summary)
    write_json("metadata/typed-producer-summary.json", {"schema": "ds02.f1.fresh089.actual-producer-summary.v1", "fresh_id": "fresh089", "rows": rows, "actual_native_frame0_qa_count": 8, "typed_completed_count": 0, "raw_arrays_read": False})
    negative_rows = []
    for case in CASES:
        source_bind = load(FRESH088 / "bindings" / f"{case}.typed-nvme-binding.json")
        output_root = Path(source_bind["typed_output_root"])
        receipt_path = output_root / "execution-receipt.json"
        stdout_path = output_root / "stdout.log"
        row = {"case_id": case, "original_fresh088_attempt_id": load(FRESH088 / "requests" / f"{case}.full-native-typed-nvme.request.json")["attempt_id"], "original_binding": str(FRESH088 / "bindings" / f"{case}.typed-nvme-binding.json"), "original_binding_sha256": sha(FRESH088 / "bindings" / f"{case}.typed-nvme-binding.json"), "preserved_unchanged": True, "array_read_by_fresh089": False}
        if receipt_path.is_file():
            row.update({"receipt": str(receipt_path), "receipt_sha256": sha(receipt_path), "receipt_data": load(receipt_path)})
        else:
            row.update({"receipt": str(receipt_path), "receipt_sha256": None, "receipt_data": None, "receipt_status": "not_present_at_source_build"})
        if stdout_path.is_file():
            text = stdout_path.read_text(encoding="utf-8", errors="replace")
            row.update({"stdout": str(stdout_path), "stdout_sha256": sha(stdout_path), "stdout_tail_max_16KiB": text[-16384:]})
        else:
            row.update({"stdout": str(stdout_path), "stdout_sha256": None, "stdout_tail_max_16KiB": None})
        negative_rows.append(row)
    write_json("metadata/fresh088-negative-summary.json", {"schema": "ds02.f1.fresh089.fresh088-negative-evidence.v1", "fresh_id": "fresh089", "purpose": "Preserve original canonical-owner converter failures/unsettled receipts without rewriting them", "rows": negative_rows, "source_arrays_read": False, "source_arrays_hashed": False, "new_attempts": "fresh089 legacy-scope requests only", "status": "historical_negative_evidence_preserved"})
    write_json("metadata/lineage.json", {
        "schema": "ds02.f1.fresh089.lineage.v1", "fresh_id": "fresh089", "family_id": "F1",
        "upstream_package": str(FRESH088), "upstream_commit": "264e14c59a80febd030e5a2da32771e7d95aed4c", "upstream_immutable": True,
        "dependency_graph": "Root283 GenCase -> Root298 GenQA -> Root299 native full window -> Root307 frame0 QA -> fresh088 canonical typed negative evidence -> fresh089 legacy-scope preflight/new typed -> fresh089 XMF -> fresh089 Root023 render",
        "new_science_cases": 0, "independent_case_count_increment": 0, "precision_or_q_n_claim": False,
        "typed_receipts_and_h5": "future; all hashes null", "raw_arrays_read": False, "jobs_launched": False, "shared_state_modified": False,
        "canonical_source_legacy_scopes_distinct": True,
    })
    write_json("metadata/candidate-registry.json", {
        "schema": "ds02.f1.fresh089.downstream-candidate-registry.v1", "family_id": "F1", "fresh_id": "fresh089",
        "scope_id": "F1_STAGE1_FIRST24_HEIGHT_EXTENSION_V1", "source_only": True, "execution_allowed": False, "launch_allowed": False,
        "actual_native_frame0_qa_completed_zero_count": 8, "fresh088_typed_failed_or_unsettled_count": 8, "fresh089_legacy_typed_completed_zero_count": 0, "xmf_completed_zero_count": 0, "render_completed_zero_count": 0,
        "typed_legacy_requests_disabled": 8, "xmf_requests_disabled": 8, "render_requests_disabled": 8, "cases": CASES,
        "dynamic_count_source": "fresh088 actual Root307 frame0 QA metadata", "future_scientific_hashes_null": True,
        "independent_case_count_increment": 0, "q_n": "not_assessed", "production_approval": "none",
    })
    readme = f"""# F1 fresh089: actual Root307 -> typed NVMe -> N3 XMF -> Root023 render handoff

This family-local source package continues fresh088 (`264e14c59a80febd030e5a2da32771e7d95aed4c`) for exactly eight already-generated F1 cases. The copied `upstream/fresh088/` files are immutable evidence. Each row reuses Root298 GenCase initial QA, Root299 native completed/0, and Root307 frame-0 native QA completed/0; actual frame counts and particle counts are read from fresh088 recorded producer metadata. No source-rounded count is substituted.

`owners/*typed-owner-xmf-adapter.json` is a metadata-only compatibility adapter. It adds the local canonical `source_owner` and SHA fields required by the unchanged legacy-aware XMF worker while retaining separate canonical/source and deferred `legacy-owner-scope.v0` identities. It does not rewrite fresh088 bytes or assign a legacy H5 scope.

fresh088's original typed attempts remain immutable negative/unsettled evidence: their canonical physical owner metadata fails the unchanged direct-converter allowlist on unclassified source-only labels (`candidate_status`/`source_axis`). For each case, fresh089 adds a metadata-only `legacy-owner-scope.v0` owner, preflights the real `_physical_condition_scope` through the approved integration `.venv`, and prepares a new disabled typed attempt ID. The full canonical physical binding is retained in `provenance/` with strict canonical validation explicitly false; no field is stripped or reclassified.

The eight XMF and eight Root023 requests are disabled, Root-owned, and source-only. XMF requests use the approved integration `.venv`, Root230 home-floor dispatch, Root142 NVMe/CPU/storage guards, dynamic N3 XYZ position/velocity shape contracts, and an explicit `xdmf` child output directory. Root023 requests use ParaView 6.1.1 with software-only offscreen environment variables and a `render` child output directory. Typed H5, converter reports, XMF manifests/XDMF, and render receipts/reports have future paths only; every future scientific/output SHA is null until Root executes the registered prerequisite. XMF binds the preflight legacy scope hash as an expected converter scope, never as the canonical source physical hash.

The builder read only JSON/XML/text metadata and executable metadata. It did not read or hash BI4/H5/CSV/VTK scientific arrays, launch GenCase/solver/converter/renderer work, modify shared runtime/ledger/registry/data, or add a new physical case.
"""
    (PACKAGE / "README.md").write_text(readme, encoding="utf-8")
    static_out = PACKAGE / "metadata/static-validation.json"
    subprocess.run([str(PYTHON), str(PACKAGE / "validate_source_contract.py"), "--package", str(PACKAGE), "--output", str(static_out)], check=True)
    manifest_rows = []
    for path in sorted(PACKAGE.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            manifest_rows.append({"path": str(path.relative_to(PACKAGE)), "bytes": path.stat().st_size, "sha256": sha(path)})
    write_json("manifest.json", {
        "schema": "ds02.f1.fresh089-actual-typed-xmf-root023-render-manifest.v1", "family_id": "F1", "fresh_id": "fresh089",
        "commit_scope": str(PACKAGE), "files": manifest_rows, "case_count": 8, "actual_native_frame0_qa_count": 8,
        "typed_request_count": 8, "xmf_request_count": 8, "render_request_count": 8,
        "typed_actual_completed_zero_count": 0, "xmf_actual_completed_zero_count": 0, "render_actual_completed_zero_count": 0,
        "dependency_graph": "Root283 -> Root298 -> Root299 -> Root307 -> fresh088 typed -> fresh089 XMF -> fresh089 Root023 render",
        "arrays_read": False, "arrays_hashed": False, "jobs_launched": False, "shared_registry_or_ledger_modified": False,
        "execution_allowed": False, "launch_allowed": False, "future_hashes_null": True,
    })
    # Final check includes the manifest itself.
    subprocess.run([str(PYTHON), str(PACKAGE / "validate_source_contract.py"), "--package", str(PACKAGE)], check=True)
    print(json.dumps({"package": str(PACKAGE), "cases": 8, "xmf_requests": 8, "render_requests": 8, "actual_root307_frame0_qa": 8, "future_typed_xmf_render_hashes_null": True}, indent=2))


if __name__ == "__main__":
    build()
