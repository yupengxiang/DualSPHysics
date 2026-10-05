#!/usr/bin/env python3
"""Build the F2 fresh100 source-only motion and metadata adapter."""
from __future__ import annotations
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

INFRA = Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
BASE = Path("/home/jade/Projects/DualSPHysics").resolve()
HERE = Path(__file__).resolve().parent
FRESH099 = INFRA / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_099_f2_stage1_first24_domain_expansion_v1"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
BIN_ROOT = BASE / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux"
GENCASE = BIN_ROOT / "GenCase_linux64"
PARTVTK = BIN_ROOT / "PartVTK_linux64"
SOLVER = BIN_ROOT / "DualSPHysics5.4_linux64"
PYTHON = INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"
LAB = INTEGRATION / "lagrangian-fluid-lab"
DECODER = BASE / "lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump"
DIRECT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
NVME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_nvme_convert_v1.py"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
ROOT142 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_home_floor_inventory_dispatch_142/root_home_floor_inventory_policy.py"
ROOT230D = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT230 = ROOT230D / "root_native_home_floor_inventory_policy.py"
ROOT230LAUNCH = ROOT230D / "launch.py"
ROOT230CONTRACT = ROOT230D / "source-policy-contract.json"
GPU = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134/ds02_root_all_idle_gpu_policy_v2.py"
RESOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
SCOPE = "F2_STAGE1_FIRST24_DOMAIN_EXPANSION_V1"
ROOT142_PROFILE = "root_home_floor_no_legacy_dataset_walk_v1"
ROOT230_PROFILE = "root_home_floor_no_legacy_dataset_walk_native_v1"
SCIENCE = {".bi4", ".h5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}
LEGACY_KEYS = ("family_id", "physical_case_id", "lineage_group_id",
               "paired_background_id", "mechanism_id", "geometry_family_id",
               "geometry", "control_family_id", "gravity_m_s2", "density_kg_m3",
               "parameters", "initial_state", "continuum_geometry")


def sha(path: Path) -> str:
    path = Path(path).resolve()
    if path.suffix.lower() in SCIENCE:
        raise ValueError(f"science artifact hash refused: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def bind(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size, "exists": True}


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def scope(owner: dict[str, Any]) -> dict[str, Any]:
    return {"schema": "legacy-owner-scope.v0",
            "semantic_binding_status": "legacy_incomplete; no cross-resolution physical claim",
            **{key: owner[key] for key in LEGACY_KEYS if key in owner}}


def motion_audit(definition: Path, motion: Path) -> dict[str, Any]:
    root = ET.parse(definition).getroot()
    node = root.find(".//casedef/motion/objreal/mvrotfile/file")
    if node is None or node.get("name") != motion.name:
        raise AssertionError(f"XML motion basename mismatch: {definition}")
    times, angles = [], []
    for raw in motion.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        a, b = raw.split(";", 1)
        times.append(float(a))
        angles.append(float(b))
    if not times or times[0] != 0.0 or abs(times[-1] - 4.0) > 1e-12:
        raise AssertionError(f"motion range mismatch: {motion}")
    if any(not (a < b) for a, b in zip(times, times[1:])):
        raise AssertionError(f"motion order mismatch: {motion}")
    if any(not math.isfinite(value) for value in times + angles):
        raise AssertionError(f"motion finite check failed: {motion}")
    if abs(angles[-1] + 105.0) > 1e-12:
        raise AssertionError(f"motion final angle mismatch: {motion}")
    return {"path": str(motion), "sha256": sha(motion), "rows": len(times),
            "time_start_s": times[0], "time_end_s": times[-1],
            "final_angle_deg": angles[-1]}


def unique(paths: list[Path]) -> list[Path]:
    result, seen = [], set()
    for path in paths:
        path = Path(path).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result


def owner_for(meta: dict[str, Any], definition: Path, motion: Path,
              metadata: Path, binding: Path) -> dict[str, Any]:
    owner = {
        "schema": "ds02.f2.stage1.fresh100.motion-adapted-owner.v1",
        "family_id": "F2", "scope_id": SCOPE,
        "case_id": meta["case_id"], "physical_case_id": meta["physical_case_id"],
        "lineage_group_id": meta["lineage_group_id"],
        "mechanism_id": meta["mechanism_id"],
        "geometry_family_id": meta["geometry_family_id"],
        "control_family_id": meta["control_family_id"],
        "geometry": meta["geometry"],
        "initial_state": meta["initial_state"],
        "continuum_geometry": {
            "receiver_low_m": meta["geometry"]["receiver_low_m"],
            "receiver_size_m": meta["geometry"]["receiver_size_m"],
            "cup_low_m": meta["geometry"]["cup_low_m"],
            "cup_size_m": meta["geometry"]["cup_size_m"],
            "tray_low_m": meta["geometry"]["tray_low_m"],
        },
        "physical_condition_sha256": meta["physical_condition_sha256"],
        "source_plan_physical_condition_sha256": meta["source_plan_physical_condition_sha256"],
        "source_physical_condition_sha256": meta["physical_condition_sha256"],
        "canonical_physical_binding_sha256": None,
        "actual_converter_physical_condition_sha256": None,
        "producer_scope_schema": "future actual legacy-owner-scope.v0",
        "semantic_binding_status": "prospective legacy scope only; no cross-resolution physical claim",
        "physical_condition_hash_scope": "source plan and future actual converter legacy scope are separate",
        "source": {
            "definition": bind(definition), "motion": bind(motion),
            "metadata": bind(metadata), "motion_gencase_binding": bind(binding),
            "initial_qa_worker": bind(HERE / "workers/f2_stage1_initial_qa_worker.py"),
        },
        "source_only": True, "execution_allowed": False, "launch_owner": "root",
        "future_hashes_null": True,
        "actual_evidence": {"gencase": None, "prepared_input_report": None,
                            "initial_qa": None, "native_solver": None,
                            "typed": None, "visual_acceptance": None},
        "production_approval": "none", "qualification": "none",
        "mass_policy": "No native counts or mass asserted; Root actual reports are authoritative",
        "independent_case_count_increment": 0,
    }
    owner["typed_scope_contract"] = {
        "converter_callable": "ds_data02_direct_convert._physical_condition_scope(owner)",
        "converter_binding_mode": "legacy-owner-scope.v0 because physical_binding is absent",
        "prospective_legacy_scope_sha256": canonical(scope(owner)),
        "actual_converter_physical_condition_sha256": None,
        "canonical_physical_binding_sha256": None,
        "canonical_grant": False,
    }
    return owner


def request_base(meta: dict[str, Any], owner: Path, files: list[Path],
                 attempt: str, native: bool = False) -> dict[str, Any]:
    files = unique(files)
    owner_data = json.loads(owner.read_text(encoding="utf-8"))
    return {
        "schema": "ds02.runner-request.v2", "family_id": "F2", "scope_id": SCOPE,
        "case_id": meta["case_id"], "physical_case_id": meta["physical_case_id"],
        "physical_condition_sha256": meta["physical_condition_sha256"],
        "source_plan_physical_condition_sha256": meta["source_plan_physical_condition_sha256"],
        "canonical_physical_binding_sha256": None,
        "prospective_legacy_scope_sha256": owner_data["typed_scope_contract"]["prospective_legacy_scope_sha256"],
        "numerical_recipe_sha256": meta["numerical_recipe_sha256"],
        "worktree_root": str(INFRA),
        "raw_output_root": str((DATA_ROOT / "families" / "F2" / meta["case_id"]).resolve()),
        "source_only": True, "root_review_required": True, "root_only": True,
        "launch_owner": "root", "launch": False, "launch_allowed": False,
        "execution_allowed": False, "disabled": True,
        "production_claim": "none", "qualification_claim": "none",
        "numerical_precision_status": "not_accepted",
        "input_files": [str(path) for path in files],
        "input_sha256": {str(path): sha(path) for path in files},
        "root_dataset_inventory_profile": ROOT230_PROFILE if native else ROOT142_PROFILE,
        "root_inventory_policy_source": str((ROOT230 if native else ROOT142).resolve()),
        "root_inventory_policy_source_sha256": sha(ROOT230 if native else ROOT142),
        "no_arrays_read": True, "no_science_payload_bound": True,
        "no_shared_registry_write": True, "no_jobs_started": True,
        "future_hashes_null": True, "attempt_id": attempt,
    }


def make_case(meta_path: Path) -> dict[str, Any]:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    cid = meta["case_id"]
    definition = Path(meta["definition_path"]).resolve()
    motion = Path(meta["motion_path"]).resolve()
    motion_audit(definition, motion)
    binding_path = HERE / "bindings" / f"{cid}.motion-gencase-binding.json"
    owner_path = HERE / "owners" / f"{cid}.motion-adapted-owner.json"
    dump(binding_path, {
        "schema": "ds02.f2.stage1.fresh100.motion-safe-gencase-binding.v1",
        "family_id": "F2", "scope_id": SCOPE, "case_id": cid,
        "physical_case_id": meta["physical_case_id"],
        "definition": str(definition), "definition_sha256": sha(definition),
        "gencase": str(GENCASE), "gencase_sha256": sha(GENCASE),
        "threads": 4, "dp_m": 0.01, "dimension": 3, "expected_fluid": None,
        "assets": [{"role": "official GenCase mvrotfile control asset",
                    "source": str(motion), "sha256": sha(motion),
                    "relative_name": motion.name, "xml_name": motion.name}],
        "source_plan_physical_condition_sha256": meta["source_plan_physical_condition_sha256"],
        "canonical_physical_binding_sha256": None,
        "predictions": {"counts": None, "count_source": "actual generated XML/prepared-input-report only",
                        "mass": None, "native_initial_qa": "pending actual arrays"},
        "source_only": True, "future_hashes_null": True,
    })
    dump(owner_path, owner_for(meta, definition, motion, meta_path, binding_path))
    worker = HERE / "workers/f2_motion_prepared_gencase_worker.py"
    qa_wrapper = HERE / "workers/f2_stage1_prepared_report_qa_worker.py"
    audit_worker = HERE / "workers/f2_prepared_report_contract_audit.py"
    qa_worker = HERE / "workers/f2_stage1_initial_qa_worker.py"
    preflight_worker = HERE / "workers/fresh100_metadata_preflight.py"
    ga = f"root-stage1-f2-{cid.lower()}-motion-gencase-100"
    qa = f"root-stage1-f2-{cid.lower()}-prepared-report-qa-100"
    native = f"root-stage1-f2-{cid.lower()}-full401-native-motion-adapted-100"
    typed = f"root-stage1-f2-{cid.lower()}-full401-typed-nvme-motion-adapted-100"
    root_dir = DATA_ROOT / "families" / "F2" / cid
    ga_root, qa_root, native_root = root_dir / ga, root_dir / qa, root_dir / native
    prepared = ga_root / "prepared"
    prefix = prepared / cid
    prepared_def = prepared / f"{cid}_Def.xml"
    prepared_report = prepared / "prepared-input-report.json"
    ga_receipt = ga_root / "execution-receipt.json"
    qa_report = qa_root / "actual-initial-qa.json"
    native_receipt = native_root / "execution-receipt.json"
    native_data = native_root / "solver_output" / "data"
    native_log = native_root / "solver_output" / "Run.out"
    common = [definition, motion, meta_path, binding_path, owner_path, HERE / "build_fresh100.py"]
    count_contract = {
        "expected_counts": {"total_particles": None, "fluid_particles": None,
                            "fixed_particles": None, "moving_particles": None},
        "count_source": "actual GenCase receipt/XML/prepared-input-report only",
        "no_forced_count": True, "no_mother_count_substitution": True,
        "mass_policy": "native mass and continuum mass remain separate; no rescale",
    }
    gfiles = common + [worker, GENCASE]
    g = request_base(meta, owner_path, gfiles, ga)
    g.update({
        "kind": "cpu", "cpu_task_kind": "gencase", "cpu_threads": 4,
        "max_wall_seconds": 600, "estimated_storage_bytes": 536870912,
        "command": [str(PYTHON), str(worker), "--binding", str(binding_path),
                    "--output-dir", "{attempt_root}/prepared"],
        "cwd": str(LAB), "count_contract": count_contract,
        "motion_asset_contract": {
            "source_definition": str(definition), "source_motion": str(motion),
            "staged_definition": str(prepared_def),
            "staged_motion": str(prepared / motion.name),
            "post_gencase_restore_and_digest_check": True,
            "source_tree_write_forbidden": True,
        },
        "expected_checks": {"actual_xml_counts_only": True, "dimension": 3,
                            "data2d": False, "dp_m": 0.01,
                            "positive_fluid_required": True,
                            "native_initial_qa_required_before_solver": True},
        "output_contract": {"generated_xml_sha256": None, "generated_bi4_sha256": None,
                            "prepared_input_report_sha256": None, "actual_counts": None},
        "disabled_reason": "Source-only fresh100; Root enables only after strict review.",
    })
    qfiles = common + [worker, qa_wrapper, audit_worker, qa_worker, PARTVTK]
    q = request_base(meta, owner_path, qfiles, qa)
    q.update({
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2,
        "max_wall_seconds": 1800, "estimated_storage_bytes": 268435456,
        "command": [str(PYTHON), str(qa_wrapper), "--case-id", cid,
                    "--definition", str(prepared_def), "--gencase-receipt", str(ga_receipt),
                    "--prepared-input-report", str(prepared_report),
                    "--prepared-report-output", "{attempt_root}/prepared-report-contract.json",
                    "--partvtk", str(PARTVTK), "--partvtk-output-dir", "{attempt_root}/partvtk",
                    "--output", "{attempt_root}/actual-initial-qa.json"],
        "cwd": str(LAB), "depends_on_attempt": ga,
        "gencase_receipt": str(ga_receipt), "gencase_receipt_sha256": None,
        "prepared_input_report": str(prepared_report),
        "prepared_input_report_sha256": None,
        "required_prepared_report_fields": [
            "schema", "case_id", "prefix", "definition_sha256", "xml_sha256",
            "bi4_sha256", "generated_xml_particle_counts", "actual_total_particles",
            "assets", "native_initial_typed_QA", "mass_evidence", "q_n",
            "production_approval", "independent_case_count_increment",
        ],
        "required_checks": ["prepared report contract completed/0", "actual GenCase success",
                            "actual 3-D XML", "finite frame zero", "positive fluid",
                            "unique Idp", "Type/Mk/Zone partition",
                            "domain/non-overlap/source lattice"],
        "output_contract": {"prepared_report_contract_sha256": None,
                            "actual_qa_report_sha256": None, "actual_counts": None,
                            "mass_kg": None},
        "disabled_reason": "Enable only after matching actual motion-safe GenCase report; no QA is prefilled.",
    })
    nfiles = common + [worker, ROOT230LAUNCH, ROOT230, ROOT230CONTRACT, GPU, RUNTIME, STRICT, SOLVER]
    n = request_base(meta, owner_path, nfiles, native, native=True)
    n.update({
        "kind": "qualification", "cpu_task_kind": "solver", "cpu_threads": 2,
        "target_gpu_index": None, "max_wall_seconds": 3600,
        "estimated_peak_gpu_mib": 8192, "estimated_storage_bytes": 8589934592,
        "command": [str(SOLVER), str(prefix), "{attempt_root}/solver_output",
                    "-tmax:4.0", "-tout:0.01"],
        "cwd": str(prepared), "gencase_prefix": str(prefix),
        "gencase_receipt": str(ga_receipt), "gencase_receipt_sha256": None,
        "initial_qa_report": str(qa_report), "initial_qa_report_sha256": None,
        "depends_on_attempts": [ga, qa],
        "solver_options_policy": "exact native command only; XML mvrotfile is authoritative; no mdbc/noslip",
        "expected_output": {"full_window_s": 4.0, "save_interval_s": 0.01,
                            "frame_count": 401, "solver_dimension": 3,
                            "particle_counts": None, "native_output_hash": None},
        "native_initial_qa_required": True,
        "root230_dispatch": {"entry": str(ROOT230LAUNCH), "entry_sha256": sha(ROOT230LAUNCH),
                             "home_floor_policy": str(ROOT230), "home_floor_policy_sha256": sha(ROOT230),
                             "gpu_policy": str(GPU), "gpu_policy_sha256": sha(GPU), "root_owned": True},
        "output_contract": {"execution_receipt_sha256": None, "run_out_sha256": None,
                            "actual_frame_count": None, "actual_particle_counts": None},
        "disabled_reason": "Enable only after actual GenCase and report-gated QA pass.",
    })
    tfiles = common + [audit_worker, qa_wrapper, DIRECT, NVME, DECODER, PARTVTK, RUNTIME, STRICT, ROOT142, RESOURCE]
    t = request_base(meta, owner_path, tfiles, typed)
    t.update({
        "kind": "cpu", "cpu_task_kind": "conversion", "cpu_threads": 2,
        "max_wall_seconds": 5400, "estimated_storage_bytes": 34359738368,
        "command": [str(PYTHON), str(NVME), "--staging-root", "/tmp/ds02-nvme-conversion",
                    "--staging-limit-bytes", str(25 * 1024**3), "--",
                    "--data-root", str(native_data), "--generated-xml", str(prefix.with_suffix(".xml")),
                    "--output", "{attempt_root}/trajectory.h5",
                    "--report", "{attempt_root}/conversion-report.json",
                    "--solver-log", str(native_log), "--solver-receipt", str(native_receipt),
                    "--gencase-receipt", str(ga_receipt), "--decoder", str(DECODER),
                    "--partvtk", str(PARTVTK), "--validation-dir", "{attempt_root}/partvtk-validation",
                    "--owner-metadata", str(owner_path), "--particle-chunk", "65536"],
        "cwd": str(LAB), "depends_on_attempts": [ga, qa, native],
        "expected_dimension": 3, "expected_native_frames": 401, "expected_particles": None,
        "native_receipt": str(native_receipt), "native_receipt_sha256": None,
        "gencase_receipt": str(ga_receipt), "gencase_receipt_sha256": None,
        "initial_qa_report": str(qa_report), "initial_qa_report_sha256": None,
        "owner_metadata": str(owner_path), "owner_metadata_sha256": sha(owner_path),
        "producer_scope_schema": "future actual legacy-owner-scope.v0; source plan remains separate",
        "physical_condition_hash_scope": {
            "source_plan_physical_condition_sha256": meta["source_plan_physical_condition_sha256"],
            "prospective_legacy_scope_sha256": json.loads(owner_path.read_text())["typed_scope_contract"]["prospective_legacy_scope_sha256"],
            "actual_converter_physical_condition_sha256": None,
            "canonical_physical_binding_sha256": None, "canonical_grant": False,
        },
        "future_input_files": [str(native_data), str(native_log), str(native_receipt),
                               str(ga_receipt), str(prepared_report),
                               str(prefix.with_suffix(".xml")), str(qa_report)],
        "future_input_sha256": {str(native_data): None, str(native_log): None,
                                str(native_receipt): None, str(ga_receipt): None,
                                str(prepared_report): None, str(prefix.with_suffix(".xml")): None,
                                str(qa_report): None},
        "future_outputs": {"conversion_report": "{attempt_root}/conversion-report.json",
                           "conversion_report_sha256": None,
                           "execution_receipt": "{attempt_root}/execution-receipt.json",
                           "execution_receipt_sha256": None,
                           "trajectory_h5": "{attempt_root}/trajectory.h5",
                           "trajectory_h5_sha256": None},
        "resource_contract": {"conversion_concurrency": 2, "cpu_threads": 2,
                              "home_min_free_bytes": 536870912000,
                              "nvme_free_space_floor_bytes": 107374182400,
                              "nvme_staging_peak_limit_bytes": 25769803776},
        "decoder_sha256": sha(DECODER),
        "output_contract": {"conversion_report_sha256": None, "trajectory_h5_sha256": None,
                            "actual_frame_count": None, "actual_particle_counts": None},
        "disabled_reason": "Future conversion only after actual GenCase, QA, native; no science output is bound.",
    })
    paths = {}
    for kind, doc in (("gencase", g), ("initial-qa", q), ("native", n), ("typed", t)):
        path = HERE / "requests" / f"{cid}-{kind}-disabled.json"
        dump(path, doc)
        paths[kind] = path
    return {
        "case_id": cid, "physical_case_id": meta["physical_case_id"],
        "physical_condition_sha256": meta["physical_condition_sha256"],
        "source_plan_physical_condition_sha256": meta["source_plan_physical_condition_sha256"],
        "receiver_x_m": meta["parameter_values"]["receiver_x_m"],
        "rotation_duration_s": meta["parameter_values"]["rotation_duration_s"],
        "definition": bind(definition), "motion": bind(motion),
        "metadata": bind(meta_path), "binding": bind(binding_path),
        "owner": bind(owner_path),
        "requests": {key: bind(path) for key, path in paths.items()},
        "source_fixture_only": True, "actual_evidence": None,
    }


def main() -> int:
    if any((HERE / name).exists() for name in ("F2_STAGE1_FRESH100_MOTION_ENTRY_MANIFEST.json",)):
        raise SystemExit("fresh100 manifest already exists; refusing overwrite")
    rows = [make_case(path) for path in sorted((FRESH099 / "source").glob("*.metadata.json"))]
    if len(rows) != 16:
        raise AssertionError(f"expected 16 fresh099 metadata files, found {len(rows)}")
    dump(HERE / "evidence/prepared-report-schema-audit.json", {
        "schema": "ds02.f2.stage1.fresh100.prepared-report-schema-audit.v1",
        "source_only": True,
        "historical_reference": {
            "path": str(next(DATA_ROOT.glob("families/F2/F2_STAGE1_FIRST8_OFFSET_RX050_DP010_SPATIAL_REFERENCE_SAVE010/*/prepared/prepared-input-report.json"), Path(""))),
            "used_as_fresh100_input": False,
        },
        "required_fields": ["schema", "case_id", "prefix", "definition_sha256", "xml_sha256",
                            "bi4_sha256", "generated_xml_particle_counts", "actual_total_particles",
                            "assets", "native_initial_typed_QA", "mass_evidence", "q_n",
                            "production_approval", "independent_case_count_increment"],
        "qa_entry_order": ["prepared-report-contract-audit", "existing-f2-PartVTK-initial-QA"],
        "science_arrays_read_by_contract_audit": False,
        "future_report_sha256": None, "future_counts": None, "future_science_hashes": None,
    })
    expected = []
    for row in rows:
        owner = json.loads(Path(row["owner"]["path"]).read_text())
        expected.append({
            "case_id": row["case_id"],
            "producer_scope_schema": "legacy-owner-scope.v0",
            "semantic_binding_status": "legacy_incomplete; no cross-resolution physical claim",
            "source_plan_physical_condition_sha256": row["source_plan_physical_condition_sha256"],
            "prospective_legacy_scope_sha256": owner["typed_scope_contract"]["prospective_legacy_scope_sha256"],
            "actual_converter_physical_condition_sha256": None,
            "canonical_physical_binding_sha256": None, "canonical_grant": False,
        })
    dump(HERE / "evidence/metadata-only-preflight.expected.json", {
        "schema": "ds02.f2.stage1.fresh100.metadata-only-preflight.expected.v1",
        "source_only": True, "actual_conversion_executed": False,
        "converter_callable": "ds_data02_direct_convert._physical_condition_scope(owner)",
        "scientific_inputs_opened": [], "cases": expected,
    })
    dump(HERE / "evidence/entry-audit.json", {
        "schema": "ds02.f2.stage1.fresh100.motion-entry-audit.v1",
        "source_only": True, "fresh099_immutable": True,
        "all_16_xmls_reference_their_case_local_dat": True,
        "fresh099_direct_request_warning": "Direct official GenCase from source directory can truncate mvrotfile; fresh099 was not modified.",
        "fresh100_worker": str((HERE / "workers/f2_motion_prepared_gencase_worker.py").resolve()),
        "staging_contract": ["copy definition into prepared", "copy exact motion .dat and verify digest",
                             "run official GenCase with staged prefix", "restore/check staged .dat",
                             "write actual prepared-input-report"],
        "qa_contract": "prepared-report audit first, then existing F2 PartVTK initial QA",
        "native_recipe": [str(SOLVER), "staged-prefix", "attempt-root/solver_output",
                          "-tmax:4.0", "-tout:0.01"],
        "typed_scope": "prospective legacy-owner-scope.v0 only; canonical not granted",
        "future_hashes_null": True, "no_jobs_or_arrays_in_build": True,
    })
    dump(HERE / "F2_STAGE1_FRESH100_MOTION_ENTRY_MANIFEST.json", {
        "schema": "ds02.f2.stage1.fresh100.motion-entry-metadata-adapter-manifest.v1",
        "fresh_id": "fresh100", "family_id": "F2", "scope_id": SCOPE,
        "source_only": True, "execution_allowed": False, "case_count": len(rows),
        "cases": sorted(rows, key=lambda row: row["case_id"]),
        "workers": {name: bind(HERE / "workers" / filename) for name, filename in {
            "motion_gencase": "f2_motion_prepared_gencase_worker.py",
            "prepared_report_audit": "f2_prepared_report_contract_audit.py",
            "initial_qa_adapter": "f2_stage1_prepared_report_qa_worker.py",
            "initial_qa": "f2_stage1_initial_qa_worker.py",
            "metadata_preflight": "fresh100_metadata_preflight.py",
        }.items()},
        "scope_contract": {"source_plan_hash_preserved": True,
                           "prospective_scope_schema": "legacy-owner-scope.v0",
                           "actual_converter_physical_condition_sha256": None,
                           "canonical_physical_binding_sha256": None,
                           "canonical_grant": False},
        "future_hashes_null": True, "all_requests_disabled": True,
        "no_shared_registry_write": True, "no_jobs_started": True, "no_science_arrays_read": True,
    })
    (HERE / "README.md").write_text(
        """# F2 fresh100 motion-entry and metadata adapter

This source-only package adapts every fresh099 case to a Root-owned
motion-safe GenCase entry. fresh099 remains untouched. Each binding stages
the XML and its exact .dat motion asset in the fresh attempt directory, runs
the official GenCase there, verifies/restores the staged asset, and emits the
actual XML/BI4 digests and prepared-input-report.json. No count, mass, QA,
native, typed, visual, Q-N, or production evidence is filled here.

The initial-QA command first reads the actual prepared-input-report JSON and
matching GenCase receipt with f2_prepared_report_contract_audit.py, then
invokes the existing bounded F2 PartVTK initial-QA worker. Output and all
scientific hashes remain null in these disabled requests.

The owner adapter intentionally omits physical_binding.v1. The exact direct
converter fallback is therefore prospective legacy-owner-scope.v0. The
source-plan hash, prospective legacy hash, and future actual converter hash
remain separate. Canonical physical binding and qualification/production
approval remain absent.

Root chain: enable one gencase request; review its actual receipt and
prepared-input-report; enable matching initial QA; review it; then use the
exact native 4 s, .01 s, 401-frame request. NVMe conversion remains disabled
until those actual receipts exist. No GenCase, PartVTK, solver, converter,
decoder, array reader, shared ledger, or shared registry was run or modified
by this package.
""", encoding="utf-8")
    print(json.dumps({"schema": "ds02.f2.stage1.fresh100.build-result.v1",
                      "package": str(HERE), "case_count": len(rows),
                      "request_count": len(rows) * 4, "source_only": True,
                      "future_hashes_null": True}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
