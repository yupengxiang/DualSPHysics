#!/usr/bin/env python3
"""Build the F4 fresh104 Root604-to-native/typed/XMF/render source handoff.

The builder reads JSON/XML/Python/text metadata only. It refuses scientific
payload reads and hashes (.bi4/.h5/.vtk/.csv/.dat). Root604 prepared reports
supply the actual GenCase counts; all native, typed, XMF, render receipts and
product hashes remain future/null.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
PACKAGE = WORKTREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_104_stage1_f4_root604_to_typed_xmf_render_v1"
FRESH102 = WORKTREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_102_stage1_f4_first48_extension_source_v1"
FRESH103 = WORKTREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/handoff_20261003/root_followup_103_stage1_f4_first48_gencase_to_native_initial_qa_v1"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT134 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134"
RESOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
DIRECT_CONVERTER = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
NVME_CONVERTER = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_nvme_convert_v1.py"
PYTHON = INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"
XMF_EXPORTER = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_repair_a_short51_actual_typed_bed_pipeline_105/workers/export_xmf.py"
ROOT023 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023"
RENDERER = ROOT023 / "render.py"
PV_PYTHON = Path("/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython")
ENV = Path("/usr/bin/env")
MESA_JSON = Path("/usr/share/glvnd/egl_vendor.d/50_mesa.json")
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
SCOPE = "F4_STAGE1_ROOT604_ACTUAL_GCASE_TO_NATIVE_TYPED_XMF_RENDER_V1"
RAW_SUFFIXES = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu", ".vtp", ".csv", ".dat"}
STATIC_SUFFIXES = {".10", ".12", ".json", ".jsonl", ".xml", ".py", ".md", ".txt", ".log", ".linux64"}
SAFE_EXECUTABLE_NAMES = {"env", "pvpython", "DualSPHysics5.4_linux64", "PartVTK_linux64"}
PUBLISHED_DECODER_SHA256 = "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
CASE_PREFIX = "root-stage1-f4-"

def fail(msg: str) -> None:
    raise RuntimeError(msg)

def load(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES:
        fail(f"scientific payload read refused: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"cannot load JSON metadata {path}") from exc
    if not isinstance(value, dict):
        fail(f"expected JSON object: {path}")
    return value

def sha(path: Path) -> str:
    path = Path(path).resolve()
    suffix = path.suffix.lower()
    if suffix in RAW_SUFFIXES:
        fail(f"scientific payload hash refused: {path}")
    # bi4_dump is a registered converter executable whose digest is already
    # published by the strict source contract.  Preserve that digest without
    # reopening the suffixless path; never generalize this exception.
    if path == DECODER.resolve():
        return PUBLISHED_DECODER_SHA256
    if suffix not in STATIC_SUFFIXES and path.name not in SAFE_EXECUTABLE_NAMES:
        fail(f"non-static input cannot be hashed: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in value)

def ref(path: Path) -> dict[str, str]:
    path = Path(path).resolve()
    if not path.is_file():
        fail(f"missing metadata input: {path}")
    return {"path": str(path), "sha256": sha(path)}

def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def unique(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = Path(path).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    return result

def safe_attempt(case_id: str, suffix: str) -> str:
    return f"{CASE_PREFIX}{case_id.lower()}-{suffix}"

def converter_module():
    spec = importlib.util.spec_from_file_location("ds02_direct_convert_fresh104_scope", DIRECT_CONVERTER)
    if spec is None or spec.loader is None:
        fail(f"cannot import direct converter: {DIRECT_CONVERTER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def classify_owner(owner: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    geometry = owner["geometry"]
    tank = geometry["tank"]
    classified_geometry: dict[str, Any] = {}
    for name, region in geometry.items():
        item = {key: copy.deepcopy(region[key]) for key in ("low_m", "size_m", "mkfluid") if key in region}
        if name == "tank":
            faces = tank.get("wall_faces_closed", [])
            item["label"] = "tank; wall_faces_closed=" + ",".join(str(face) for face in faces)
        elif "label" in region:
            item["label"] = region["label"]
        classified_geometry[name] = item
    initial = owner["initial_state"]
    source_regions = {
        name: copy.deepcopy(classified_geometry[name])
        for name in ("pool", "drop")
        if name in classified_geometry
    }
    controls = owner["controls"]
    classified_initial = {
        "source_regions": source_regions,
        "velocities_m_per_s": copy.deepcopy(initial["velocities_m_per_s"]),
        "source_labels": copy.deepcopy(initial["source_labels"]),
        "initial_mass_by_source_kg": None,
        "continuum_mass_by_source_kg": None,
        "initial_mass_total_kg": None,
        "mass_policy": "native mass remains authoritative; continuum comparison is separate; no rescale",
    }
    classified_controls = {
        key: copy.deepcopy(controls[key])
        for key in ("step_algorithm", "kernel", "viscosity", "density_dt", "density_dt_value", "boundary")
    }
    rhop0 = float(report["actual_generated_constants"]["rhop0"]["value"])
    return {
        "schema": "ds-data-02.physical-binding.v1",
        "family_id": owner["family_id"],
        "physical_case_id": owner["physical_case_id"],
        "mechanism_id": owner["mechanism_id"],
        "geometry_family_id": owner["geometry_family_id"],
        "control_family_id": owner["control_family_id"],
        "lineage_group_id": owner["lineage_group_id"],
        "geometry": classified_geometry,
        "initial_state": classified_initial,
        "controls": classified_controls,
        "gravity_m_s2": copy.deepcopy(controls["gravity_m_s2"]),
        "density_kg_m3": rhop0,
        "parameters": copy.deepcopy(owner["parameters"]),
        "event_window": {
            "time_start_s": 0.0,
            "time_end_s": float(owner["solver_recipe"]["time_max_s"]),
            "sequence": ["initial static pool", "falling drop"],
            "expected_first_contact_range_s": None,
            "right_censor_policy": "prospective native window; no Q-N or production claim before actual evidence",
        },
        "open_inlet": bool(controls["open_inlet"]),
        "periodic_boundary": bool(controls["periodic_boundary"]),
        "mass_policy": "native_mass_unscaled_with_continuum_comparison",
    }

def actual_cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for basic_path in sorted((FRESH103 / "bindings").glob("*.gencase-basic-input-binding.json")):
        basic = load(basic_path)
        case_id = str(basic["case_id"])
        owner_ref = basic["source_owner"]
        owner_path = Path(owner_ref["path"]).resolve()
        owner = load(owner_path)
        gencase = basic["gencase"]
        receipt_path = Path(gencase["receipt"]["path"]).resolve()
        report_path = Path(gencase["prepared_report"]["path"]).resolve()
        xml_path = Path(gencase["generated_xml"]["path"]).resolve()
        bi4_path = Path(gencase["generated_bi4"]["path"]).resolve()
        root604_request_path = Path(basic["actual_root604_gencase_request"]["path"]).resolve()
        root604_request = load(root604_request_path)
        receipt = load(receipt_path)
        report = load(report_path)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            fail(f"{case_id}: Root604 receipt is not completed/0")
        if report.get("case_id") != case_id or report.get("schema") != "ds02.root.actual-native-source-preflight.v1":
            fail(f"{case_id}: prepared report identity/schema drift")
        if report.get("actual_generated_constants", {}).get("data2d", {}).get("value") != "false":
            fail(f"{case_id}: Root604 report is not actual 3-D")
        counts = report.get("generated_xml_particle_counts")
        total = report.get("actual_total_particles")
        if not isinstance(counts, dict) or not isinstance(total, int) or total <= 0:
            fail(f"{case_id}: prepared report lacks actual counts")
        count_row = {
            "fixed": int(counts["fixed"]),
            "moving": int(counts.get("moving", 0)),
            "floating": int(counts.get("floating", 0)),
            "fluid": int(counts["fluid"]),
        }
        if sum(count_row.values()) != total:
            fail(f"{case_id}: report count sum does not equal actual total")
        xml_sha = str(report["xml_sha256"])
        if not valid_sha(xml_sha) or not xml_path.is_file() or sha(xml_path) != xml_sha:
            fail(f"{case_id}: prepared XML hash does not close")
        bi4_sha = str(report["bi4_sha256"])
        if not valid_sha(bi4_sha):
            fail(f"{case_id}: missing actual BI4 producer digest")
        if not bi4_path.is_file():
            fail(f"{case_id}: prepared BI4 path missing")
        fresh_basic_request = FRESH103 / "requests" / f"{case_id}.gencase-basic-initial-qa-103-disabled.request.json"
        fresh_basic_binding = basic_path
        fresh_frame_binding = FRESH103 / "bindings" / f"{case_id}.native-frame0-input-binding.json"
        fresh_frame_request = FRESH103 / "requests" / f"{case_id}.native-frame0-partvtk-vz-103-disabled.request.json"
        for path in (fresh_basic_request, fresh_frame_binding, fresh_frame_request, root604_request_path):
            if not path.is_file():
                fail(f"{case_id}: missing future/reference binding {path}")
        converter = converter_module()
        legacy_scope = converter._physical_condition_scope(owner)
        classified = classify_owner(owner, report)
        converter._validate_physical_binding(classified)
        canonical_hash = converter.canonical_hash(classified)
        legacy_hash = converter.canonical_hash(legacy_scope)
        if canonical_hash == str(owner["physical_condition_sha256"]):
            fail(f"{case_id}: derived converter hash reused source owner hash")
        rows.append({
            "case_id": case_id,
            "owner_path": owner_path,
            "owner": owner,
            "basic_path": basic,
            "basic_binding_path": basic_path.resolve(),
            "fresh_basic_request": fresh_basic_request.resolve(),
            "fresh_frame_binding": fresh_frame_binding.resolve(),
            "fresh_frame_request": fresh_frame_request.resolve(),
            "root604_request_path": root604_request_path,
            "root604_request": root604_request,
            "raw_receipt_path": receipt_path,
            "raw_receipt": receipt,
            "prepared_report_path": report_path,
            "report": report,
            "xml_path": xml_path,
            "bi4_path": bi4_path,
            "counts": count_row,
            "total": total,
            "xml_sha256": xml_sha,
            "bi4_producer_sha256": bi4_sha,
            "classified_physical_binding": classified,
            "converter_scope_sha256": canonical_hash,
            "legacy_scope_sha256": legacy_hash,
            "source_owner_physical_condition_sha256": str(owner["physical_condition_sha256"]),
            "source_plan_condition_sha256": str(owner["source_plan_condition_sha256"]),
            "root604_binding_path": Path(str(root604_request["binding"])).resolve(),
        })
    if len(rows) != 24:
        fail(f"fresh103/Root604 must provide 24 cases, found {len(rows)}")
    if len({row["case_id"] for row in rows}) != 24:
        fail("duplicate case IDs")
    return rows

def static_paths(row: dict[str, Any], extra: list[Path]) -> list[Path]:
    paths = [
        row["owner_path"], row["fresh_basic_request"], row["basic_binding_path"],
        row["fresh_frame_binding"], row["fresh_frame_request"],
        row["root604_request_path"], row["root604_binding_path"],
        row["raw_receipt_path"], row["prepared_report_path"], row["xml_path"],
        FRESH102 / "source-plan.json", Path(row["owner"]["source_definition"]["path"]),
        PACKAGE / "metadata/fresh104-stage-contract.json",
        PACKAGE / "metadata/converter-physical-scope-contract.json",
        PACKAGE / "evidence/converter-physical-scope-preflight.json",
        RUNTIME, STRICT, RESOURCE, ROOT230 / "launch.py",
        ROOT230 / "root_native_home_floor_inventory_policy.py",
        ROOT230 / "source-policy-contract.json",
        ROOT134 / "ds02_root_all_idle_gpu_policy_v2.py",
        DIRECT_CONVERTER, NVME_CONVERTER, PYTHON, XMF_EXPORTER, RENDERER,
        ROOT023 / "README.md", SOLVER, PARTVTK, DECODER,
        PACKAGE / f"evidence/{row['case_id']}.gencase-semantic-evidence.json",
        PACKAGE / f"bindings/{row['case_id']}.converter-owner.json",
    ]
    return unique(paths + extra)

def hash_inputs(paths: list[Path]) -> dict[str, str]:
    return {str(path.resolve()): sha(path) for path in paths}

def gate_template(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "WAIT_ROOT616_ACTUAL_BASIC_QA",
        "required": True,
        "actual_attempt_id": None,
        "actual_binding": None,
        "actual_report": None,
        "source_request_template": ref(row["fresh_basic_request"]),
        "source_worker_template": ref(row["basic_binding_path"]),
        "pass_must_be_actual": "completed/0 and all basic checks true; Root604 GenCase semantic evidence is not a substitute for basic QA",
    }

def frame_gate(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "WAIT_NATIVE_AND_FRAME0_QA",
        "required": True,
        "actual_attempt_id": None,
        "actual_binding": ref(row["fresh_frame_binding"]),
        "actual_request": ref(row["fresh_frame_request"]),
        "actual_report": None,
        "actual_report_sha256": None,
        "raw_mk_type_and_velocity_must_be_observed": True,
        "gencase_velocity_is_not_native_evidence": True,
    }

def base_request(row: dict[str, Any], attempt: str, kind: str, task_kind: str | None,
                 command: list[str], cwd: Path, max_wall: int, storage: int,
                 inputs: list[Path], deferred: list[Path], output: dict[str, Any],
                 reason: str) -> dict[str, Any]:
    req: dict[str, Any] = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F4",
        "case_id": row["case_id"],
        "attempt_id": attempt,
        "kind": kind,
        "command": command,
        "cwd": str(cwd.resolve()),
        "worktree_root": str(INTEGRATION),
        "max_wall_seconds": max_wall,
        "cpu_threads": 2,
        "estimated_storage_bytes": storage,
        "input_files": [str(p.resolve()) for p in inputs],
        "input_sha256": hash_inputs(inputs),
        "deferred_input_files": [str(Path(p).resolve()) for p in deferred],
        "deferred_input_sha256": {str(Path(p).resolve()): None for p in deferred},
        "expected_outputs": output,
        "disabled": True,
        "execution_allowed": False,
        "launch": False,
        "launch_allowed": False,
        "source_only": True,
        "root_only": True,
        "launch_owner": "root",
        "root_review_required": True,
        "independent_case_count_increment": 0,
        "disabled_reason": reason,
        "arrays_read_by_source": False,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
        "future_hashes": {"execution_receipt_sha256": None, "output_sha256": None},
    }
    if task_kind is not None:
        req["cpu_task_kind"] = task_kind
    return req

def gencase_semantic(row: dict[str, Any]) -> dict[str, Any]:
    report = row["report"]
    return {
        "schema": "ds02.f4.fresh104.gencase-semantic-evidence.v1",
        "case_id": row["case_id"],
        "attempt_id": row["basic_path"]["gencase"]["attempt_id"],
        "status": "completed",
        "returncode": 0,
        "raw_receipt_immutable": True,
        "raw_execution_receipt": ref(row["raw_receipt_path"]),
        "prepared_input_report": ref(row["prepared_report_path"]),
        "generated_xml": {"path": str(row["xml_path"]), "sha256": row["xml_sha256"]},
        "generated_bi4": {
            "path": str(row["bi4_path"]),
            "producer_sha256": row["bi4_producer_sha256"],
            "content_rehashed_by_source": False,
        },
        "actual_particle_counts": row["counts"],
        "actual_total_particles": row["total"],
        "fluid_particles": row["counts"]["fluid"],
        "fixed_particles": row["counts"]["fixed"],
        "moving_particles": row["counts"]["moving"],
        "floating_particles": row["counts"]["floating"],
        "solver_dimension_from_gencase": 3,
        "data2d": False,
        "actual_constants": report["actual_generated_constants"],
        "native_initial_typed_QA": "pending actual native/frame0 evidence",
        "mass_evidence": report.get("mass_evidence"),
        "q_n": "not_granted",
        "production_approval": "none",
        "arrays_read_by_source": False,
        "semantic_adapter": True,
        "semantic_adapter_boundary": "Counts and 3-D status are copied from the actual prepared report; raw receipt bytes are never rewritten or treated as containing these fields.",
    }

def main() -> None:
    if PACKAGE.exists():
        fail(f"refusing to overwrite existing package: {PACKAGE}")
    for path in (DIRECT_CONVERTER, NVME_CONVERTER, XMF_EXPORTER, RENDERER, ROOT230 / "launch.py", SOLVER, PARTVTK, DECODER):
        if not path.is_file():
            fail(f"required executable/source missing: {path}")
    PACKAGE.mkdir(parents=True)
    for dirname in ("bindings", "requests", "evidence", "metadata", "render", "tests", "workers"):
        (PACKAGE / dirname).mkdir()
    rows = actual_cases()

    stage_contract = {
        "schema": "ds02.f4.fresh104.stage-contract.v1",
        "scope_id": SCOPE,
        "family_id": "F4",
        "case_count": 24,
        "execution_allowed": False,
        "arrays_read_or_hashed_by_source": False,
        "science_payloads_read_by_source": [],
        "jobs_started_by_source": False,
        "shared_registry_write": False,
        "source_only": True,
        "recipe": {
            "dp_m": 0.01, "time_max_s": 1.2, "time_out_s": 0.001,
            "native_frame_count": 1201, "solver_options": ["-tmax:1.2", "-tout:0.001"],
            "no_forcing": True, "no_mdbc": True, "cpu_threads": 2,
        },
        "actual_gencase": {
            "source": "Root604 prepared-input-report.json",
            "counts_are_dynamic_from_report": True,
            "report_sha256_is_recorded": True,
            "raw_receipt_is_preserved": True,
            "semantic_adapter_does_not_rewrite_raw_receipt": True,
        },
        "physical_scope": {
            "source_owner_scope": "legacy-owner-scope.v0; original source condition hash retained",
            "derived_converter_scope": "ds-data-02.physical-binding.v1; real converter allowlist validation and canonical hash",
            "source_owner_hash_must_not_be_reused": True,
            "canonical_physical_scope_is_not_QN_or_production_approval": True,
        },
        "gates": {
            "native": "Root616 actual per-case basic QA completed/0, then Root230 native",
            "typed": "matching native completed/0 and independent Root530 frame-0 raw Mk/Type/velocity audit",
            "xmf": "matching typed completed/0 and audited conversion report",
            "render": "matching XMF completed/0; Root023 full 1201-frame software render",
        },
        "historical_negative_evidence": {
            "continuum_volume": "retained diagnostic only; no mass rescaling",
            "dp_lattice": "retained diagnostic only; no Q-N or precision grant",
        },
    }
    dump(PACKAGE / "metadata/fresh104-stage-contract.json", stage_contract)
    dump(PACKAGE / "metadata/converter-physical-scope-contract.json", {
        "schema": "ds02.f4.fresh104.converter-physical-scope-contract.v1",
        "converter": ref(DIRECT_CONVERTER),
        "real_functions": ["_physical_condition_scope", "_validate_physical_binding", "canonical_hash"],
        "original_owner_semantics": "Original fresh102 owner has schema physical-binding.v1 at top level but no nested physical_binding object; real converter therefore returns legacy-owner-scope.v0.",
        "derived_semantics": "fresh104 classifies only allowlisted physical fields into a new nested physical_binding.v1; source owner and source-plan hashes remain separate.",
        "unclassified_fields_are_not_silently_carried": True,
        "source_owner_hash_must_not_be_reused": True,
    })

    # Write per-case semantic evidence and converter-owner sidecars.
    preflight_rows = []
    for row in rows:
        semantic_path = PACKAGE / f"evidence/{row['case_id']}.gencase-semantic-evidence.json"
        owner_sidecar_path = PACKAGE / f"bindings/{row['case_id']}.converter-owner.json"
        dump(semantic_path, gencase_semantic(row))
        owner_sidecar = {
            "schema": "ds02.f4.fresh104.converter-owner.v1",
            "case_id": row["case_id"],
            "family_id": "F4",
            "physical_case_id": row["owner"]["physical_case_id"],
            "physical_binding": row["classified_physical_binding"],
            "physical_binding_sha256": row["converter_scope_sha256"],
            "canonical_physical_binding_sha256": row["converter_scope_sha256"],
            "legacy_owner_scope_sha256": row["legacy_scope_sha256"],
            "source_owner": ref(row["owner_path"]),
            "source_owner_physical_condition_sha256": row["source_owner_physical_condition_sha256"],
            "source_plan_condition_sha256": row["source_plan_condition_sha256"],
            "condition_hash_semantics": {
                "converter_hash_scope": "sha256(canonical JSON of physical_binding.v1 only)",
                "source_owner_hash_is_retained_separately": True,
                "source_plan_hash_is_retained_separately": True,
                "equality_claim": "none",
            },
            "actual_gencase": {
                "prepared_report": ref(row["prepared_report_path"]),
                "raw_receipt": ref(row["raw_receipt_path"]),
                "actual_counts": row["counts"],
                "actual_total_particles": row["total"],
                "generated_xml": {"path": str(row["xml_path"]), "sha256": row["xml_sha256"]},
                "generated_bi4_producer_sha256": row["bi4_producer_sha256"],
            },
            "source_only": True,
            "execution_allowed": False,
            "q_n_status": "not_granted",
            "precision_status": "not_accepted",
            "production_approval": "none",
        }
        dump(owner_sidecar_path, owner_sidecar)
        preflight_rows.append({
            "case_id": row["case_id"],
            "original_owner": ref(row["owner_path"]),
            "original_owner_physical_condition_sha256": row["source_owner_physical_condition_sha256"],
            "legacy_scope_sha256": row["legacy_scope_sha256"],
            "derived_physical_binding": ref(owner_sidecar_path),
            "derived_physical_binding_sha256": row["converter_scope_sha256"],
            "converter_validate_physical_binding": "pass",
            "converter_canonical_hash": row["converter_scope_sha256"],
            "source_owner_hash_reused": False,
            "arrays_read_or_hashed_by_preflight": False,
        })
    dump(PACKAGE / "evidence/converter-physical-scope-preflight.json", {
        "schema": "ds02.f4.fresh104.converter-physical-scope-preflight.v1",
        "converter": ref(DIRECT_CONVERTER),
        "claim_boundary": "Metadata-only allowlist/hash preflight; no converter execution and no scientific payload read/hash.",
        "cases": preflight_rows,
        "all_pass": True,
        "arrays_read_or_hashed_by_preflight": False,
        "jobs_started_by_preflight": False,
    })

    # Write stage bindings before requests so request input closures can hash them.
    request_rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []
    stage_paths: dict[str, dict[str, Path]] = {}
    for row in rows:
        case = row["case_id"]
        owner_sidecar = PACKAGE / f"bindings/{case}.converter-owner.json"
        semantic_path = PACKAGE / f"evidence/{case}.gencase-semantic-evidence.json"
        native_attempt = safe_attempt(case, "full1201-native-root230-fresh104")
        typed_attempt = safe_attempt(case, "full1201-typed-nvme-fresh104")
        xmf_attempt = safe_attempt(case, "full1201-xmf-fresh104")
        render_attempt = safe_attempt(case, "full1201-root023-render-fresh104")
        native_root = DATA / "families/F4" / case / native_attempt
        typed_root = DATA / "families/F4" / case / typed_attempt
        xmf_root = DATA / "families/F4" / case / xmf_attempt
        render_root = DATA / "families/F4" / case / render_attempt
        native_path = PACKAGE / f"bindings/{case}.native-binding.json"
        typed_path = PACKAGE / f"bindings/{case}.typed-binding.json"
        xmf_path = PACKAGE / f"bindings/{case}.xmf-binding.json"
        render_path = PACKAGE / f"bindings/{case}.render-binding.json"
        typed_request_ref_path = PACKAGE / f"requests/{case}.full1201-typed-nvme-fresh104-disabled.request.json"
        xmf_request_ref_path = PACKAGE / f"requests/{case}.full1201-xmf-fresh104-disabled.request.json"
        stage_paths[case] = {"owner": owner_sidecar, "semantic": semantic_path, "native": native_path, "typed": typed_path, "xmf": xmf_path, "render": render_path, "typed_request": typed_request_ref_path, "xmf_request": xmf_request_ref_path}
        actual_counts = row["counts"]
        basic_gate = gate_template(row)
        frame_gate_data = frame_gate(row)
        native_binding = {
            "schema": "ds02.f4.fresh104.native-binding.v1",
            "fresh_id": "fresh104",
            "scope_id": SCOPE,
            "case_id": case,
            "physical_case_id": case,
            "physical_condition_sha256": row["converter_scope_sha256"],
            "source_owner_physical_condition_sha256": row["source_owner_physical_condition_sha256"],
            "source_plan_condition_sha256": row["source_plan_condition_sha256"],
            "physical_binding": ref(owner_sidecar),
            "root604_gencase": {
                "request": ref(row["root604_request_path"]),
                "receipt": ref(row["raw_receipt_path"]),
                "prepared_report": ref(row["prepared_report_path"]),
                "generated_xml": {"path": str(row["xml_path"]), "sha256": row["xml_sha256"]},
                "generated_bi4": {"path": str(row["bi4_path"]), "producer_sha256": row["bi4_producer_sha256"], "read_by_source": False},
                "semantic_evidence": ref(semantic_path),
            },
            "actual_particle_counts": actual_counts,
            "actual_total_particles": row["total"],
            "solver_dimension_from_gencase": 3,
            "native_recipe": {
                "dp_m": 0.01, "time_max_s": 1.2, "time_out_s": 0.001,
                "native_frame_count": 1201, "solver_options": ["-tmax:1.2", "-tout:0.001"],
                "no_forcing": True, "no_mdbc": True, "native_types": {"fixed": [0], "moving": [], "floating": [], "fluid": [3]},
            },
            "basic_qa_gate": basic_gate,
            "frame0_gate": frame_gate_data,
            "native_status": "WAIT_ROOT616_BASIC_QA",
            "native_receipt": {"path": str(native_root / "execution-receipt.json"), "sha256": None, "status": None},
            "output_root": str(native_root),
            "future_hashes": {"native_receipt_sha256": None, "frame0_report_sha256": None, "solver_output_sha256": None},
            "source_only": True, "execution_allowed": False, "arrays_read_by_source": False,
            "mass_policy": {"native_mass_authoritative": True, "continuum_comparison_separate": True, "mass_rescaled": False},
            "precision_status": "not_accepted", "q_n_status": "not_granted", "production_approval": "none",
        }
        dump(native_path, native_binding)
        typed_binding = {
            "schema": "ds02.f4.fresh104.typed-binding.v1",
            "fresh_id": "fresh104", "scope_id": SCOPE, "case_id": case, "physical_case_id": case,
            "physical_condition_sha256": row["converter_scope_sha256"],
            "source_owner_physical_condition_sha256": row["source_owner_physical_condition_sha256"],
            "source_plan_condition_sha256": row["source_plan_condition_sha256"],
            "physical_binding": ref(owner_sidecar),
            "gencase_semantic_evidence": ref(semantic_path),
            "native_binding": {"path": str(native_path.resolve()), "sha256": sha(native_path)},
            "native_solver": {
                "attempt_id": native_attempt, "output_root": str(native_root),
                "data_root": str(native_root / "solver_output/data"),
                "execution_receipt": str(native_root / "execution-receipt.json"),
                "status": "future_completed0_required", "receipt_sha256": None,
                "expected_frames": 1201, "time_window_s": 1.2, "save_interval_s": 0.001,
            },
            "native_frame0_gate": frame_gate_data,
            "gencase_actual_evidence": {
                "actual_particle_counts": actual_counts, "actual_total_particles": row["total"],
                "dimension": 3, "generated_xml": str(row["xml_path"]), "generated_xml_sha256": row["xml_sha256"],
                "gencase_receipt": str(row["raw_receipt_path"]), "gencase_receipt_sha256": sha(row["raw_receipt_path"]),
                "prepared_report": str(row["prepared_report_path"]),
                "generated_bi4_producer_sha256": row["bi4_producer_sha256"],
            },
            "typed_converter": {
                "nvme_wrapper": str(NVME_CONVERTER), "direct_converter": str(DIRECT_CONVERTER),
                "official_decoder": str(DECODER), "official_partvtk": str(PARTVTK),
                "cpu_threads": 2, "nvme_staging_root": "/tmp/ds02-nvme-conversion-cache",
                "nvme_peak_bytes": 24 * 1024**3, "conversion_concurrency_cap": 2,
                "physical_scope_preflight": "real _validate_physical_binding pass; derived scope only",
            },
            "vector_contract": {"field": "velocity", "semantic_type": "N3", "components": ["vx", "vy", "vz"], "coordinate_frame": "DualSPHysics Cartesian (x,y,z)"},
            "actual_typed_result": None,
            "future_hashes": {"trajectory_h5_sha256": None, "conversion_report_sha256": None, "execution_receipt_sha256": None},
            "source_only": True, "execution_allowed": False, "arrays_read_by_source": False,
            "precision_status": "not_accepted", "q_n_status": "not_granted", "production_approval": "none",
        }
        dump(typed_path, typed_binding)
        xmf_binding = {
            "schema": "ds02.f4.fresh104.xmf-binding.v1",
            "fresh_id": "fresh104", "scope_id": SCOPE, "case_id": case, "physical_case_id": case,
            "physical_condition_sha256": row["converter_scope_sha256"],
            "source_owner_physical_condition_sha256": row["source_owner_physical_condition_sha256"],
            "source_plan_condition_sha256": row["source_plan_condition_sha256"],
            "physical_binding": ref(owner_sidecar),
            "typed_binding": {"path": str(typed_path.resolve()), "sha256": sha(typed_path)},
            "typed_request": {"path": str(typed_request_ref_path.resolve()), "sha256": None}, "typed_receipt": str(typed_root / "execution-receipt.json"),
            "trajectory_h5": str(typed_root / "trajectory.h5"),
            "conversion_report": str(typed_root / "conversion-report.json"),
            "native_receipt": str(native_root / "execution-receipt.json"),
            "expected_frames": 1201, "expected_particles": row["total"], "expected_dimension": 3,
            "physical_window_s": [0.0, 1.2], "vector_semantic_type": "N3",
            "future_hashes": {"case_xmf_sha256": None, "manifest_sha256": None, "execution_receipt_sha256": None},
            "execution_allowed": False, "source_only": True, "arrays_read_by_source": False,
        }
        dump(xmf_path, xmf_binding)
        render_binding = {
            "schema": "ds02.f4.fresh104.root023-render-binding.v1",
            "fresh_id": "fresh104", "scope_id": SCOPE, "case_id": case, "physical_case_id": case,
            "physical_condition_sha256": row["converter_scope_sha256"],
            "source_owner_physical_condition_sha256": row["source_owner_physical_condition_sha256"],
            "source_plan_condition_sha256": row["source_plan_condition_sha256"],
            "physical_binding": ref(owner_sidecar),
            "typed_binding": {"path": str(typed_path.resolve()), "sha256": sha(typed_path)},
            "xmf_binding": {"path": str(xmf_path.resolve()), "sha256": sha(xmf_path)},
            "xmf_request": {"path": str(xmf_request_ref_path.resolve()), "sha256": None},
            "manifest": str(xmf_root / "manifest.json"), "case_xmf": str(xmf_root / "case.xmf"),
            "native_reader": "Root023 native renderer; full 1201 saved frames",
            "vector_contract": {"field": "velocity", "semantic_type": "N3", "components": ["vx", "vy", "vz"]},
            "future_hashes": {"pvsm_sha256": None, "gif_sha256": None, "report_sha256": None, "execution_receipt_sha256": None},
            "execution_allowed": False, "source_only": True, "arrays_read_by_source": False,
        }
        dump(render_path, render_binding)

    # Generate singleton requests. Each case has one request per stage.
    for row in rows:
        case = row["case_id"]
        paths = stage_paths[case]
        owner_sidecar = paths["owner"]
        semantic_path = paths["semantic"]
        native_path = paths["native"]
        typed_path = paths["typed"]
        xmf_path = paths["xmf"]
        render_path = paths["render"]
        native_attempt = safe_attempt(case, "full1201-native-root230-fresh104")
        typed_attempt = safe_attempt(case, "full1201-typed-nvme-fresh104")
        xmf_attempt = safe_attempt(case, "full1201-xmf-fresh104")
        render_attempt = safe_attempt(case, "full1201-root023-render-fresh104")
        native_root = DATA / "families/F4" / case / native_attempt
        typed_root = DATA / "families/F4" / case / typed_attempt
        xmf_root = DATA / "families/F4" / case / xmf_attempt
        render_root = DATA / "families/F4" / case / render_attempt
        prefix = str(row["report"]["prefix"])
        native_inputs = static_paths(row, [native_path])
        native_deferred = [row["bi4_path"], native_root / "solver_output/data", native_root / "execution-receipt.json"]
        native_req = base_request(
            row, native_attempt, "qualification", None,
            [str(SOLVER), prefix, "{attempt_root}/solver_output", "-tmax:1.2", "-tout:0.001"],
            row["xml_path"].parent, 14400, 64 * 1024**3, native_inputs, native_deferred,
            {"output_root": str(native_root), "data_root": str(native_root / "solver_output/data"), "execution_receipt": str(native_root / "execution-receipt.json"), "full_native_frames": 1201, "native_receipt_sha256": None, "frame0_report_sha256": None},
            "Enable only after Root616 supplies actual per-case basic QA completed/0 and Root resolves a live non-foreign Root230 GPU lease. Root604 raw GenCase receipt remains immutable; semantic counts come from its prepared report. No historical negative or source declaration substitutes for QA.",
        )
        native_req.update({
            "solver_recipe": {"dp_m": 0.01, "time_max_s": 1.2, "time_out_s": 0.001, "native_frame_count": 1201, "solver_options": ["-tmax:1.2", "-tout:0.001"], "no_forcing": True, "no_mdbc": True},
            "expected_native_frames": 1201, "estimated_peak_gpu_mib": 8192,
            "gencase_receipt": str(semantic_path.resolve()), "gencase_receipt_sha256": sha(semantic_path),
            "gencase_raw_receipt": ref(row["raw_receipt_path"]), "gencase_prepared_report": ref(row["prepared_report_path"]),
            "gencase_actual_evidence": {"semantic_adapter": ref(semantic_path), "raw_receipt": ref(row["raw_receipt_path"]), "prepared_report": ref(row["prepared_report_path"]), "actual_counts": row["counts"], "actual_total_particles": row["total"], "solver_dimension_from_gencase": 3, "data2d": False, "generated_xml": {"path": str(row["xml_path"]), "sha256": row["xml_sha256"]}, "generated_bi4": {"path": str(row["bi4_path"]), "producer_sha256": row["bi4_producer_sha256"], "content_rehashed_by_source": False}},
            "physical_case_id": case, "physical_condition_sha256": row["converter_scope_sha256"], "source_owner_physical_condition_sha256": row["source_owner_physical_condition_sha256"], "source_plan_condition_sha256": row["source_plan_condition_sha256"],
            "physical_binding": ref(owner_sidecar), "native_binding": ref(native_path),
            "basic_qa_gate": json.loads((native_path).read_text())["basic_qa_gate"],
            "root230_profile": {"entry": ref(ROOT230 / "launch.py"), "home_free_gib_floor": 500, "nvme_free_gib_floor": 100, "nvme_peak_gib": 24, "foreign_gpu_protection": True, "uuid_selection": "Root resolves live non-foreign UUID at enable time", "solver_concurrency_cap": 8},
            "depends_on_attempts": [safe_attempt(case, "gencase-basic-initial-qa-103")],
            "root_actual_launch_source": ref(ROOT230 / "launch.py"),
        })
        native_req_path = PACKAGE / f"requests/{case}.full1201-native-root230-fresh104-disabled.request.json"
        dump(native_req_path, native_req)

        typed_inputs = static_paths(row, [typed_path, native_path, native_req_path])
        typed_deferred = [row["bi4_path"], native_root / "solver_output/data", native_root / "execution-receipt.json", typed_root / "trajectory.h5", typed_root / "conversion-report.json", typed_root / "execution-receipt.json"]
        typed_command = [
            str(PYTHON), str(NVME_CONVERTER), "--staging-root", "/tmp/ds02-nvme-conversion-cache",
            "--staging-limit-bytes", str(24 * 1024**3), "--",
            str(DIRECT_CONVERTER), "--data-root", str(native_root / "solver_output/data"),
            "--generated-xml", str(row["xml_path"]), "--output", "{attempt_root}/trajectory.h5",
            "--report", "{attempt_root}/conversion-report.json", "--decoder", str(DECODER),
            "--partvtk", str(PARTVTK), "--validation-dir", "{attempt_root}/partvtk-validation",
            "--solver-log", str(native_root / "solver_output/Run.out"),
            "--solver-receipt", str(native_root / "execution-receipt.json"),
            "--gencase-receipt", str(semantic_path.resolve()), "--owner-metadata", str(owner_sidecar.resolve()),
        ]
        typed_req = base_request(
            row, typed_attempt, "cpu", "conversion", typed_command, INTEGRATION / "lagrangian-fluid-lab", 14400, 24 * 1024**3,
            typed_inputs, typed_deferred,
            {"output_root": str(typed_root), "trajectory_h5": str(typed_root / "trajectory.h5"), "conversion_report": str(typed_root / "conversion-report.json"), "execution_receipt": str(typed_root / "execution-receipt.json"), "all_sha256": None},
            "Enable only after matching Root230 native completed/0 and independent Root530 frame-0 raw Mk/Type/velocity QA. Use CPU2 and NVMe conversion cap2; no duplicate native launch.",
        )
        typed_req.update({
            "physical_case_id": case, "physical_condition_sha256": row["converter_scope_sha256"], "source_owner_physical_condition_sha256": row["source_owner_physical_condition_sha256"], "source_plan_condition_sha256": row["source_plan_condition_sha256"],
            "physical_binding": ref(owner_sidecar), "owner_metadata": str(owner_sidecar.resolve()),
            "gencase_receipt": str(semantic_path.resolve()), "gencase_receipt_sha256": sha(semantic_path),
            "gencase_raw_receipt": ref(row["raw_receipt_path"]), "generated_xml": {"path": str(row["xml_path"]), "sha256": row["xml_sha256"]},
            "actual_particle_counts": row["counts"], "actual_total_particles": row["total"], "solver_dimension_from_gencase": 3,
            "native_receipt": {"path": str(native_root / "execution-receipt.json"), "sha256": None}, "native_data_root": str(native_root / "solver_output/data"),
            "native_binding": ref(native_path), "native_frame0_gate": json.loads((paths["typed"]).read_text())["native_frame0_gate"],
            "converter_scope": {"schema": "ds-data-02.physical-binding.v1", "physical_binding_sha256": row["converter_scope_sha256"], "legacy_owner_scope_sha256": row["legacy_scope_sha256"], "source_owner_hash_not_reused": True, "preflight": "real converter _validate_physical_binding pass"},
            "expected_native": {"frames": 1201, "time_window_s": 1.2, "save_interval_s": 0.001, "particles": row["total"], "fluid_particles": row["counts"]["fluid"], "dimension": 3},
            "typed_vector_contract": {"field": "velocity", "semantic_type": "N3", "components": ["vx", "vy", "vz"]},
            "depends_on_attempts": [native_attempt],
        })
        typed_req_path = PACKAGE / f"requests/{case}.full1201-typed-nvme-fresh104-disabled.request.json"
        dump(typed_req_path, typed_req)

        xmf_inputs = static_paths(row, [xmf_path, typed_path, typed_req_path, native_path, native_req_path])
        xmf_deferred = [typed_root / "trajectory.h5", typed_root / "conversion-report.json", typed_root / "execution-receipt.json", xmf_root / "case.xmf", xmf_root / "manifest.json", xmf_root / "execution-receipt.json"]
        xmf_command = [str(PYTHON), str(XMF_EXPORTER), "--binding", str(xmf_path), "--output-dir", "{attempt_root}"]
        xmf_req = base_request(
            row, xmf_attempt, "cpu", "conversion", xmf_command, INTEGRATION / "lagrangian-fluid-lab", 7200, 2 * 1024**3,
            xmf_inputs, xmf_deferred,
            {"output_root": str(xmf_root), "case_xmf": str(xmf_root / "case.xmf"), "manifest": str(xmf_root / "manifest.json"), "execution_receipt": str(xmf_root / "execution-receipt.json"), "all_sha256": None},
            "Enable only after this case's typed converter independently reports completed/0 and its report has full 1201 frames, 3-D shape, N3 velocity and identity lifecycle. XMF is a derived view, never a new case.",
        )
        xmf_req.update({
            "physical_case_id": case, "physical_condition_sha256": row["converter_scope_sha256"], "source_owner_physical_condition_sha256": row["source_owner_physical_condition_sha256"], "source_plan_condition_sha256": row["source_plan_condition_sha256"],
            "physical_binding": ref(owner_sidecar), "typed_binding": ref(typed_path), "typed_request": ref(typed_req_path),
            "typed_receipt": str(typed_root / "execution-receipt.json"), "trajectory_h5": str(typed_root / "trajectory.h5"), "conversion_report": str(typed_root / "conversion-report.json"), "native_receipt": str(native_root / "execution-receipt.json"),
            "expected_frames": 1201, "expected_particles": row["total"], "physical_window_s": [0.0, 1.2], "vector_semantic_type": "N3",
            "depends_on_attempts": [typed_attempt],
        })
        xmf_req_path = PACKAGE / f"requests/{case}.full1201-xmf-fresh104-disabled.request.json"
        dump(xmf_req_path, xmf_req)

        render_inputs = static_paths(row, [render_path, xmf_path, xmf_req_path, typed_path, typed_req_path, native_path, native_req_path])
        render_deferred = [xmf_root / "case.xmf", xmf_root / "manifest.json", xmf_root / "execution-receipt.json", typed_root / "trajectory.h5", typed_root / "conversion-report.json", typed_root / "execution-receipt.json", render_root / "case.pvsm", render_root / "full_saved_animation.gif", render_root / "paraview-full-animation-report.json", render_root / "execution-receipt.json"]
        render_command = [str(ENV), "VTK_SMP_MAX_THREADS=2", "LP_NUM_THREADS=2", "LIBGL_ALWAYS_SOFTWARE=1", "MESA_LOADER_DRIVER_OVERRIDE=llvmpipe", "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json", "VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow", "QT_QPA_PLATFORM=offscreen", "OMP_NUM_THREADS=2", str(PV_PYTHON), "--force-offscreen-rendering", str(RENDERER), "--manifest", str(xmf_root / "manifest.json"), "--output-dir", "{attempt_root}"]
        render_req = base_request(
            row, render_attempt, "cpu", "audit", render_command, INTEGRATION / "lagrangian-fluid-lab", 14400, 12 * 1024**3,
            render_inputs, render_deferred,
            {"output_root": str(render_root), "case_pvsm": str(render_root / "case.pvsm"), "full_saved_animation_gif": str(render_root / "full_saved_animation.gif"), "report": str(render_root / "paraview-full-animation-report.json"), "execution_receipt": str(render_root / "execution-receipt.json"), "all_sha256": None},
            "Enable only after this case's XMF completed/0 and Root023 can inspect all 1201 frames with its software renderer. Preserve every native field and N3 velocity; no diagnostic shortcut.",
        )
        render_req.update({
            "physical_case_id": case, "physical_condition_sha256": row["converter_scope_sha256"], "source_owner_physical_condition_sha256": row["source_owner_physical_condition_sha256"], "source_plan_condition_sha256": row["source_plan_condition_sha256"],
            "physical_binding": ref(owner_sidecar), "typed_binding": ref(typed_path), "xmf_binding": ref(xmf_path), "xmf_request": ref(xmf_req_path),
            "manifest": str(xmf_root / "manifest.json"), "case_xmf": str(xmf_root / "case.xmf"), "expected_frames": 1201, "expected_particles": row["total"], "vector_semantic_type": "N3", "depends_on_attempts": [xmf_attempt],
        })
        render_req_path = PACKAGE / f"requests/{case}.full1201-root023-render-fresh104-disabled.request.json"
        dump(render_req_path, render_req)

        request_rows.extend([
            {"case_id": case, "kind": "native", "path": str(native_req_path), "sha256": sha(native_req_path), "disabled": True},
            {"case_id": case, "kind": "typed", "path": str(typed_req_path), "sha256": sha(typed_req_path), "disabled": True},
            {"case_id": case, "kind": "xmf", "path": str(xmf_req_path), "sha256": sha(xmf_req_path), "disabled": True},
            {"case_id": case, "kind": "render", "path": str(render_req_path), "sha256": sha(render_req_path), "disabled": True},
        ])
        case_rows.append({
            "case_id": case, "physical_condition_sha256": row["converter_scope_sha256"],
            "source_owner_physical_condition_sha256": row["source_owner_physical_condition_sha256"],
            "source_plan_condition_sha256": row["source_plan_condition_sha256"],
            "actual_counts": row["counts"], "actual_total_particles": row["total"],
            "root604_report": ref(row["prepared_report_path"]),
            "converter_owner": ref(owner_sidecar),
            "native_request": ref(native_req_path), "typed_request": ref(typed_req_path),
            "xmf_request": ref(xmf_req_path), "render_request": ref(render_req_path),
            "future_hashes": {"native_receipt": None, "typed_h5": None, "typed_report": None, "typed_receipt": None, "xmf": None, "render": None},
        })

    # Update source bindings after requests exist only with request refs; request input
    # hashes deliberately do not include these post-update binding bytes.
    dump(PACKAGE / "requests/index.json", {
        "schema": "ds02.f4.fresh104.request-index.v1", "scope_id": SCOPE, "family_id": "F4",
        "case_count": 24, "request_count": len(request_rows), "all_disabled": True,
        "requests": request_rows, "independent_case_count_increment": 0,
        "native_concurrency_cap": 8, "conversion_concurrency_cap": 2, "cpu_threads": 2,
    })
    dump(PACKAGE / "source-binding.json", {
        "schema": "ds02.f4.fresh104.source-binding.v1", "scope_id": SCOPE, "family_id": "F4",
        "case_count": 24, "request_count": len(request_rows), "actual_gencase_status": "Root604 completed/0 for all 24",
        "actual_counts_source": "each Root604 prepared-input-report.json; no forced source count",
        "source_owner_vs_converter_scope": "original owner physical_condition_sha256, legacy scope hash, and derived converter physical_binding.v1 hash are all separate",
        "stage_order": ["Root616 basic QA", "Root230 native 1201", "Root530 frame0 QA", "typed NVMe conversion", "N3 XMF", "Root023 render"],
        "requests": request_rows, "cases": case_rows,
        "future_hashes_all_null": True, "arrays_read_by_source": False, "jobs_started_by_source": False,
        "shared_registry_write_by_source": False, "precision_status": "not_accepted", "q_n_status": "not_granted", "production_approval": "none",
        "resource_window": ref(RESOURCE), "home_free_gib_floor": 500, "nvme_free_gib_floor": 100, "nvme_peak_gib": 24,
    })
    dump(PACKAGE / "manifest.json", {
        "schema": "ds02.f4.fresh104.manifest.v1", "scope_id": SCOPE, "family_id": "F4",
        "case_count": 24, "request_count": len(request_rows), "disabled_request_count": len(request_rows),
        "actual_root604_gencase_completed0": 24, "actual_counts_from_prepared_reports": True,
        "future_hashes_null": True, "source_only": True, "execution_allowed": False,
        "physical_scope_preflight": ref(PACKAGE / "evidence/converter-physical-scope-preflight.json"),
        "request_index": ref(PACKAGE / "requests/index.json"), "source_binding": ref(PACKAGE / "source-binding.json"),
        "claim_boundary": "No native, frame0, typed, XMF, render, precision, Q-N, visual or production result is claimed.",
    })
    dump(PACKAGE / "metadata/fresh104-upstream.json", {
        "schema": "ds02.f4.fresh104.upstream.v1", "fresh102": ref(FRESH102 / "source-plan.json"),
        "fresh103": ref(FRESH103 / "manifest.json"), "root230": ref(ROOT230 / "launch.py"),
        "root604_reports": 24, "root616_basic_qa": "future Root-owned per-case evidence; no guessed path",
        "old_negative_evidence": "fresh103 stage contract preserves continuum and DP-lattice diagnostics",
    })
    (PACKAGE / "README.md").write_text("""# F4 fresh104 Root604 to native, typed, XMF and Root023 handoff

This source-only package binds all 24 actual Root604 GenCase reports. Counts,
3-D status, generated XML digest, and BI4 producer digest come from each
prepared-input-report.json. The raw Root604 receipt remains immutable; the
per-case semantic evidence sidecar only exposes report-backed fields required
by the qualification runtime.

Each case has four independent disabled singleton requests:

1. Root230 full native, DP=.01, 1.2 s, .001 s, 1201 frames, no forcing/no mDBC;
2. CPU2/NVMe-cap2 direct typed conversion with official PartVTK validation;
3. N3 temporal XMF export;
4. Root023 full 1201-frame software rendering.

Native enablement requires the actual Root616 basic QA for that case and a
live non-foreign Root230 UUID. Typed conversion additionally requires native
completed/0 and the separate Root530 frame-0 raw Mk/Type/velocity audit.
All future native/typed/XMF/render receipts and product hashes are null.

The original fresh102 owner/source-plan condition hashes are retained. The
original owner is legacy scope under the converter. fresh104 derives an
allowlisted physical-binding.v1 object and records the real converter
_validate_physical_binding/canonical_hash result in the preflight evidence.
The derived converter hash is kept separate from source hashes and does not
grant canonical qualification, Q-N, precision, visual, or production status.

The package never reads or hashes BI4/H5/VTK/CSV/DAT payloads, launches jobs,
or writes shared state.
""")
    (PACKAGE / "render/n3-vector-spec.json").write_text(json.dumps({
        "schema": "ds02.f4.fresh104.n3-vector-spec.v1", "field": "velocity",
        "semantic_type": "N3", "components": ["vx", "vy", "vz"],
        "coordinate_frame": "DualSPHysics Cartesian (x,y,z)", "preserve_all_native_fields": True,
    }, indent=2, sort_keys=True) + "\n")
    # A standalone metadata-only verifier for Root review; it never opens science payloads.
    (PACKAGE / "workers/verify_converter_scope.py").write_text("""#!/usr/bin/env python3
import importlib.util, json, sys
from pathlib import Path
DIRECT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py")
def load(p): return json.loads(Path(p).read_text())
def main():
    if len(sys.argv) != 3: raise SystemExit("usage: verify_converter_scope.py OWNER_JSON OUTPUT_JSON")
    owner = load(sys.argv[1])
    spec = importlib.util.spec_from_file_location("ds02_direct_convert_scope_review", DIRECT)
    mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod)
    original = mod._physical_condition_scope(owner)
    if "physical_binding" not in owner: original_scope = "legacy-owner-scope.v0"
    else: original_scope = owner["physical_binding"].get("schema")
    derived = owner["physical_binding"]
    mod._validate_physical_binding(derived)
    result = {"schema": "ds02.f4.fresh104.converter-scope-verifier.v1", "original_scope": original_scope, "legacy_scope_sha256": mod.canonical_hash(original), "derived_scope_sha256": mod.canonical_hash(derived), "validated": True, "arrays_read_or_hashed": False, "jobs_started": False}
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2, sort_keys=True) + "\\n")
if __name__ == "__main__": main()
""")
    (PACKAGE / "tests/test_source_contract.py").write_text("""import json
from pathlib import Path
P = Path(__file__).resolve().parents[1]
def test_fresh104_disabled_and_closed():
    idx = json.loads((P / "requests/index.json").read_text())
    assert idx["case_count"] == 24 and idx["request_count"] == 96
    assert idx["all_disabled"] is True
    for row in idx["requests"]:
        req = json.loads(Path(row["path"]).read_text())
        assert req["disabled"] and req["execution_allowed"] is False and req["launch"] is False
        assert req["input_files"] and set(req["input_sha256"]) == set(req["input_files"])
        assert all(v == 64 for v in req["input_sha256"].values())
        assert all(v is None for v in req["expected_outputs"].values() if isinstance(v, (str, type(None))))
""")
    (PACKAGE / "workers/validate_fresh104_source.py").write_text("""#!/usr/bin/env python3
import json
from pathlib import Path
P = Path(__file__).resolve().parents[1]
RAW = {".bi4",".h5",".hdf5",".vtk",".vtu",".vtp",".csv",".dat"}
def load(p): return json.loads(Path(p).read_text())
def main():
    idx = load(P/"requests/index.json")
    assert idx["case_count"] == 24 and idx["request_count"] == 96 and idx["all_disabled"]
    assert all(len(set(row) - {"case_id","kind","path","sha256","disabled"}) == 0 for row in idx["requests"])
    for row in idx["requests"]:
        req = load(row["path"])
        assert req["disabled"] and not req["launch"] and not req["execution_allowed"]
        assert req["family_id"] == "F4" and req["cpu_threads"] == 2
        assert req["input_files"] and set(req["input_sha256"]) == set(req["input_files"])
        for path in req["input_files"]:
            assert Path(path).suffix.lower() not in RAW
            assert req["input_sha256"][path] == __import__("hashlib").sha256(Path(path).read_bytes()).hexdigest()
        assert all(value is None for value in req["expected_outputs"].values() if isinstance(value,(str,type(None))))
        assert all(value is None for value in req["future_hashes"].values())
    manifest = load(P/"manifest.json")
    assert manifest["actual_root604_gencase_completed0"] == 24 and manifest["future_hashes_null"]
    pre = load(P/"evidence/converter-physical-scope-preflight.json")
    assert pre["all_pass"] and len(pre["cases"]) == 24
    assert all(row["source_owner_hash_reused"] is False for row in pre["cases"])
    print("fresh104 source contract: PASS (24 cases, 96 disabled singleton requests, Root604 actual report counts, converter scope preflight)")
if __name__ == "__main__": main()
""")
    for p in (PACKAGE / "workers/verify_converter_scope.py", PACKAGE / "workers/validate_fresh104_source.py"):
        p.chmod(0o755)
    print(json.dumps({"package": str(PACKAGE), "cases": 24, "requests": len(request_rows), "root604_completed0": 24, "future_hashes_null": True}, indent=2))

if __name__ == "__main__":
    main()
