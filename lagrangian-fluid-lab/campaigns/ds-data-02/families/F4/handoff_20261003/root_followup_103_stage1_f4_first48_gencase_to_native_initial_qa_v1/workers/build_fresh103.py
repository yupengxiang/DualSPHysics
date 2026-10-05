#!/usr/bin/env python3
"""Build the F4 fresh103 GenCase-to-native source-only handoff.

This builder reads only source JSON/XML/Python metadata.  It never opens,
copies, or hashes BI4/H5/VTK/CSV/DAT scientific payloads and never launches a
worker.  Runtime adapters materialize the existing Root502/Root530 worker
bindings only after Root supplies real GenCase/native receipts.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics").resolve()
FAMILY_ROOT = WORKTREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4"
HANDOFF = FAMILY_ROOT / "handoff_20261003"
PACKAGE = HANDOFF / "root_followup_103_stage1_f4_first48_gencase_to_native_initial_qa_v1"
FRESH102 = HANDOFF / "root_followup_102_stage1_f4_first48_extension_source_v1"
FRESH095 = HANDOFF / "root_followup_095_stage1_f4_gencase_basic_initial_qa_v1"
FRESH096 = HANDOFF / "root_followup_096_stage1_f4_root502_basicqa_to_root230_full1201_native_v1"
FRESH097 = HANDOFF / "root_followup_097_stage1_f4_native_frame0_partvtk_vz_to_typed_v1"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4").resolve()
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
ROOT134 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_first24_eight_solver_resource_policy_134"
ROOT604 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_distinct_second24_fresh102_genuine_GenCase_604"
ROOT605 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f4_second24_gencase604_first1_then_CPU2_cap4_controller_605"
RUNTIME = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
STRICT = INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
RESOURCE = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64").resolve()
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64").resolve()
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f8_r008_safe_bi4_decoder_v1.py").resolve()
PYTHON = INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"
PARTVTK_REGISTERED = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump").resolve()
GENCASE_BIN = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64").resolve()

DP = 0.01
TIME_MAX = 1.2
TIME_OUT = 0.001
FRAMES = 1201
RAW_SUFFIXES = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv", ".dat"}
STATIC_SUFFIXES = {".json", ".jsonl", ".xml", ".py", ".md", ".txt", ".log", ".linux64", ".10", ""}
HEX = set("0123456789abcdef")


def load_json(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f"scientific payload cannot be loaded as metadata: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    path = Path(path).resolve()
    suffix = path.suffix.lower()
    if suffix in RAW_SUFFIXES:
        raise ValueError(f"scientific payload hash refused: {path}")
    if suffix not in STATIC_SUFFIXES and path not in {SOLVER, PARTVTK}:
        raise ValueError(f"unsupported source input suffix: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ref(path: Path) -> dict[str, str]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path)}


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX


def unique(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw).resolve()
        key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def assert_source_xml(definition: Path, owner: dict[str, Any], row: dict[str, Any]) -> None:
    tree = ET.parse(definition)
    root = tree.getroot()
    geom = root.find(".//geometry/definition")
    if geom is None or abs(float(geom.attrib.get("dp", "nan")) - DP) > 1e-12:
        raise ValueError(f"source definition DP drift: {definition}")
    data2d = root.find(".//execution/constants/data2d")
    if data2d is None:
        data2d = root.find(".//data2d")
    if data2d is not None and str(data2d.attrib.get("value", "")).lower() != "false":
        raise ValueError(f"source definition is explicitly 2-D: {definition}")
    velocity = root.find(".//initials/velocity[@mkfluid='1']")
    if velocity is None:
        raise ValueError(f"source definition lacks falling-drop velocity: {definition}")
    expected = owner["initial_state"]["velocities_m_per_s"]["mkfluid:1"]
    observed = [float(velocity.attrib.get(axis, "nan")) for axis in ("x", "y", "z")]
    if any(abs(a - b) > 1e-12 for a, b in zip(observed, expected)):
        raise ValueError(f"source velocity drift: {definition}")
    drop = owner["geometry"]["drop"]
    main = root.find("./casedef/geometry/commands/mainlist")
    if main is None:
        raise ValueError(f"source definition lacks mainlist: {definition}")
    active: int | None = None
    found: dict[int, ET.Element] = {}
    for node in list(main):
        if node.tag == "setmkfluid":
            active = int(node.attrib["mk"])
        elif node.tag == "setmkbound":
            active = None
        elif node.tag == "drawbox" and active is not None:
            found[active] = node
    point = found.get(1)
    if point is None or point.find("point") is None:
        raise ValueError(f"source definition lacks mkfluid=1 drawbox: {definition}")
    p = point.find("point")
    expected_low = drop["low_m"]
    observed_low = [float(p.attrib[axis]) for axis in ("x", "y", "z")]
    if any(abs(a - b) > 1e-12 for a, b in zip(observed_low, expected_low)):
        raise ValueError(f"source drop placement drift: {definition}")
    if row["definition"]["sha256"] != sha(definition):
        raise ValueError(f"fresh102 definition digest drift: {definition}")


def source_refs(row: dict[str, Any]) -> tuple[Path, Path, Path, Path, dict[str, Any], dict[str, Any]]:
    case = str(row["case_id"])
    definition = Path(row["definition"]["path"]).resolve()
    owner_path = FRESH102 / "owners" / f"{case}.owner.json"
    source_request = FRESH102 / "requests" / f"{case}-gencase.request.json"
    actual_request = ROOT604 / f"{case}-gencase-request.json"
    effective_request = actual_request if actual_request.is_file() else source_request
    if not definition.is_file() or not owner_path.is_file() or not source_request.is_file() or not effective_request.is_file():
        raise FileNotFoundError(case)
    owner = load_json(owner_path)
    gen_request = load_json(effective_request)
    gen_request["_fresh102_source_request_path"] = str(source_request)
    gen_request["_root604_binding_path"] = str(ROOT604 / f"{case}-gencase-binding.json")
    if owner.get("physical_case_id") != row["physical_case_id"]:
        raise ValueError(f"owner physical ID drift: {case}")
    if owner.get("physical_condition_sha256") != row["physical_condition_sha256"]:
        raise ValueError(f"owner physical SHA drift: {case}")
    if gen_request.get("attempt_id") is None or gen_request.get("cpu_task_kind") != "gencase":
        raise ValueError(f"GenCase request contract drift: {case}")
    assert_source_xml(definition, owner, row)
    return definition, owner_path, effective_request, FRESH102 / "source-plan.json", owner, gen_request


def source_static_paths() -> list[Path]:
    return unique([
        FRESH102 / "source-plan.json",
        FRESH095 / "workers/run_f4_fresh095_gencase_basic_initial_qa.py",
        FRESH095 / "metadata/fresh095-gencase-plan.json",
        FRESH095 / "metadata/fresh095-partvtk-contract.json",
        FRESH095 / "metadata/fresh095-stage1-contract.json",
        FRESH096 / "metadata/fresh096-native-plan.json",
        FRESH096 / "metadata/fresh096-root230-contract.json",
        FRESH096 / "metadata/fresh096-stage-contract.json",
        FRESH097 / "workers/native_frame0_partvtk_vz_audit.py",
        FRESH097 / "metadata/fresh097-manifest.json",
        FRESH097 / "metadata/fresh097-root230-contract.json",
        FRESH097 / "metadata/fresh097-stage-contract.json",
        ROOT230 / "launch.py",
        ROOT230 / "root_native_home_floor_inventory_policy.py",
        ROOT230 / "source-policy-contract.json",
        ROOT134 / "ds02_root_all_idle_gpu_policy_v2.py",
        RUNTIME,
        STRICT,
        RESOURCE,
        ROOT604 / "actual-root-disjoint24-genuineGenCase-enable-review.json",
        ROOT605 / "controller-result.json",
        DECODER,
        SOLVER,
        PARTVTK,
    ])


def future_paths(case: str, gen_attempt: str) -> dict[str, str]:
    gen_root = DATA_ROOT / case / gen_attempt
    return {
        "gencase_root": str(gen_root),
        "generated_xml": str(gen_root / "prepared" / f"{case}.xml"),
        "generated_bi4": str(gen_root / "prepared" / f"{case}.bi4"),
        "prepared_report": str(gen_root / "prepared" / "prepared-input-report.json"),
        "gencase_receipt": str(gen_root / "execution-receipt.json"),
    }


def attempts(case: str, gen_attempt: str) -> dict[str, str]:
    stem = case.lower()
    return {
        "gencase": gen_attempt,
        "basic_qa": f"root-stage1-f4-{stem}-gencase-basic-initial-qa-103",
        "native": f"root-stage1-f4-{stem}-full1201-native-root230-fresh103",
        "frame0": f"root-stage1-f4-{stem}-native-frame0-partvtk-vz-fresh103",
    }


def source_geometry(owner: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "tank": owner["geometry"]["tank"],
        "pool": owner["geometry"]["pool"],
        "drop": owner["geometry"]["drop"],
        "declared_gap_parameter_m": row["parameters"]["gap_m"],
        "clearance_policy": "Root basic QA must measure inclusive source extrema and drop/pool separation; source gap is not a continuum-volume or lattice pass.",
    }


def recipe() -> dict[str, Any]:
    return {
        "dp_m": DP,
        "time_max_s": TIME_MAX,
        "time_out_s": TIME_OUT,
        "native_frame_count": FRAMES,
        "solver_options": ["-tmax:1.2", "-tout:0.001"],
        "no_forcing": True,
        "no_mdbc": True,
        "omp_threads": 2,
        "native_types": {"fixed": [0], "floating": [], "fluid": [3], "moving": []},
    }


def write_upstream_metadata() -> None:
    PACKAGE.mkdir(parents=True, exist_ok=True)
    (PACKAGE / "metadata").mkdir(parents=True, exist_ok=True)
    marker = {
        "schema": "ds02.f4.fresh103.marker-semantics.v1",
        "source_scope": {
            "xml_mkfluid": "GenCase source-region label used for XML drawbox/UID partition and declared velocity.",
            "basic_qa_raw_markers": "Root502-compatible pre-solver worker does not claim raw Mk/Type; it uses generated XML plus Posd/Idp to derive source partition.",
            "native_frame0_raw_markers": "Root530-compatible post-solver worker must observe official PartVTK raw Mk, Type, Idp and saved Vel rows.",
        },
        "historical_root530_observation": {
            "mkfluid_0_to_native_mk": 1,
            "mkfluid_1_to_native_mk": 2,
            "status": "historical observed mapping only; not copied into future QA pass and must be checked against each actual PartVTK report",
        },
        "velocity_scope": {
            "source_declared": "owner.initial_state.velocities_m_per_s is an XML declaration only",
            "native_required": "frame0 PartVTK Vel.z rows are the only solver initial-velocity evidence",
            "drop_vector": "future native observation must compare raw rows for the actual Mk resolved by the registered worker",
        },
        "future_counts_and_hashes": "all null until Root completes the matching GenCase/native/QA attempt",
    }
    dump(PACKAGE / "metadata/fresh103-marker-semantics.json", marker)
    upstream = {
        "schema": "ds02.f4.fresh103.upstream-contracts.v1",
        "source_only": True,
        "fresh095_basic_worker": ref(FRESH095 / "workers/run_f4_fresh095_gencase_basic_initial_qa.py"),
        "fresh095_stage_contract": ref(FRESH095 / "metadata/fresh095-stage1-contract.json"),
        "fresh095_partvtk_contract": ref(FRESH095 / "metadata/fresh095-partvtk-contract.json"),
        "fresh096_root230_contract": ref(FRESH096 / "metadata/fresh096-root230-contract.json"),
        "fresh096_native_plan": ref(FRESH096 / "metadata/fresh096-native-plan.json"),
        "fresh096_stage_contract": ref(FRESH096 / "metadata/fresh096-stage-contract.json"),
        "fresh097_frame0_worker": ref(FRESH097 / "workers/native_frame0_partvtk_vz_audit.py"),
        "fresh097_root230_contract": ref(FRESH097 / "metadata/fresh097-root230-contract.json"),
        "fresh097_stage_contract": ref(FRESH097 / "metadata/fresh097-stage-contract.json"),
        "root604": {
            "review": ref(ROOT604 / "actual-root-disjoint24-genuineGenCase-enable-review.json"),
            "controller": ref(ROOT605 / "controller-result.json"),
            "request_dir": str(ROOT604),
            "lineage": "actual Root604 GenCase requests and prepared reports; source counts remain null until adapter materialization",
        },
        "worker_reuse": {
            "basic": "fresh095 Root502-compatible worker after metadata materialization",
            "frame0": "fresh097 Root530-compatible official PartVTK worker after native receipt/count/marker materialization",
        },
    }
    dump(PACKAGE / "metadata/fresh103-upstream-contracts.json", upstream)
    stage = {
        "schema": "ds02.f4.fresh103.stage-contract.v1",
        "scope_id": "F4_STAGE1_FIRST48_FRESH102_GCASE_BASIC_TO_NATIVE_FRAME0_V1",
        "family_id": "F4",
        "case_count": 24,
        "source_only": True,
        "execution_allowed": False,
        "launch_allowed": False,
        "jobs_started_by_source": False,
        "shared_registry_write": False,
        "arrays_read_or_hashed_by_source": False,
        "science_payloads_read_by_source": [],
        "future_hashes_null": True,
        "recipe": recipe(),
        "stages": {
            "gencase": "fresh102 individual GenCase request remains upstream and disabled",
            "basic_initial_qa": "fresh095 Root502-compatible pre-solver audit; source position/UID/count/finite/clearance checks; actual counts come from future prepared report",
            "native_solver": "Root230 full 1.2 s / 0.001 s / 1201-frame request disabled until matching basic QA completed/0",
            "native_frame0": "fresh097 Root530-compatible official PartVTK audit disabled until matching native completed/0; raw Mk/Type/Vel.z are required",
        },
        "gen_case_vs_native_scope": {
            "gencase_scope": "generated XML/BI4 source placement, UID partition, 3-D and declared initial velocity",
            "native_scope": "saved solver frame-0 data and official PartVTK raw marker/velocity evidence",
            "no_substitution": "GenCase XML velocity and source placement never substitute for native frame-0 velocity or raw Mk/Type",
        },
        "mass_and_lattice_policy": {
            "native_vs_nominal_mass": "report separately",
            "mass_rescaled": False,
            "continuum_volume_gate": False,
            "dp_lattice_gate": False,
            "historical_negative_diagnostics_preserved": True,
        },
        "historical_negative_evidence": {
            "root216": "old internal-gap native initial QA population/lattice negative remains evidence only",
            "root471": "old strict continuum/lattice diagnostic negative remains evidence only",
            "neither_is_a_future_case_gate": True,
        },
    }
    dump(PACKAGE / "metadata/fresh103-stage-contract.json", stage)
    gencase_contract = {
        "schema": "ds02.f4.fresh103.gencase-basic-contract.v1",
        "worker": str(PACKAGE / "workers/run_fresh103_basic_initial_qa.py"),
        "upstream_worker": str(FRESH095 / "workers/run_f4_fresh095_gencase_basic_initial_qa.py"),
        "pre_solver": True,
        "required_actual_inputs": ["completed/0 GenCase receipt", "prepared-input-report.json", "generated XML", "BI4 producer attestation"],
        "checks": ["actual 3-D", "finite positions", "unique complete UID", "actual source counts", "XML inclusive extrema", "drop/pool non-overlap", "tank containment", "recipe/source invariants"],
        "raw_mk_type_observed": False,
        "type_partition": "XML fixed/fluid blocks plus Idp ranges; not raw Mk/Type evidence",
        "initial_velocity": "XML declaration only; native frame-0 velocity remains downstream",
        "actual_counts": "null in source templates; materializer requires actual prepared report/receipt values",
        "mass_rescaled": False,
        "continuum_or_dp_lattice_gate": False,
    }
    dump(PACKAGE / "metadata/fresh103-gencase-basic-contract.json", gencase_contract)
    native_contract = {
        "schema": "ds02.f4.fresh103.native-contract.v1",
        "worker_policy": str(ROOT230 / "source-policy-contract.json"),
        "recipe": recipe(),
        "native_gate": "matching basic QA report pass and actual GenCase evidence; no old diagnostic or boolean substitutes",
        "root230": {
            "profile": "root_live_all_idle_uuid_leased_eight_solver_v2",
            "home_free_gib_floor": 500,
            "nvme_free_gib_floor": 100,
            "nvme_peak_gib": 24,
            "foreign_gpu_protection": True,
            "uuid_selection": "Root resolves a live UUID at enable time; source selects none",
        },
        "estimated_storage": "64 GiB provisional upper bound; Root must recompute from actual prepared report before enablement",
        "future_native_receipt": None,
        "future_frame0_report": None,
    }
    dump(PACKAGE / "metadata/fresh103-native-contract.json", native_contract)
    frame_contract = {
        "schema": "ds02.f4.fresh103.native-frame0-contract.v1",
        "worker": str(PACKAGE / "workers/run_fresh103_frame0_audit.py"),
        "upstream_worker": str(FRESH097 / "workers/native_frame0_partvtk_vz_audit.py"),
        "requires": ["matching native execution receipt status completed and returncode 0", "actual GenCase counts/XML/report", "official PartVTK raw Mk/Type/Idp/Vel rows"],
        "raw_fields": ["Mk", "Type", "Idp", "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]"],
        "native_count_policy": "report observed frame-0 rows; never pad or force GenCase count",
        "mk_mapping": "historical Root530 map is only a starting metadata hint; actual PartVTK rows must be checked",
        "velocity": "compare raw native rows against the actual resolved raw-Mk map; XML declaration alone is insufficient",
        "source_only": True,
        "future_report_sha256": None,
    }
    dump(PACKAGE / "metadata/fresh103-native-frame0-contract.json", frame_contract)


def base_static_for_case(case: str, definition: Path, owner_path: Path, source_request: Path, plan_path: Path) -> list[Path]:
    return unique([
        definition,
        owner_path,
        source_request,
        FRESH102 / "requests" / f"{case}-gencase.request.json",
        (ROOT604 / f"{case}-gencase-binding.json"),
        plan_path,
        PACKAGE / "metadata/fresh103-stage-contract.json",
        PACKAGE / "metadata/fresh103-marker-semantics.json",
        PACKAGE / "metadata/fresh103-upstream-contracts.json",
        PACKAGE / "metadata/fresh103-gencase-basic-contract.json",
        PACKAGE / "metadata/fresh103-native-contract.json",
        PACKAGE / "metadata/fresh103-native-frame0-contract.json",
        FRESH095 / "workers/run_f4_fresh095_gencase_basic_initial_qa.py",
        FRESH095 / "metadata/fresh095-gencase-plan.json",
        FRESH095 / "metadata/fresh095-partvtk-contract.json",
        FRESH095 / "metadata/fresh095-stage1-contract.json",
        FRESH096 / "metadata/fresh096-native-plan.json",
        FRESH096 / "metadata/fresh096-root230-contract.json",
        FRESH096 / "metadata/fresh096-stage-contract.json",
        FRESH097 / "workers/native_frame0_partvtk_vz_audit.py",
        FRESH097 / "metadata/fresh097-manifest.json",
        FRESH097 / "metadata/fresh097-root230-contract.json",
        FRESH097 / "metadata/fresh097-stage-contract.json",
        ROOT230 / "launch.py",
        ROOT230 / "root_native_home_floor_inventory_policy.py",
        ROOT230 / "source-policy-contract.json",
        ROOT134 / "ds02_root_all_idle_gpu_policy_v2.py",
        RUNTIME,
        STRICT,
        RESOURCE,
        DECODER,
        SOLVER,
        PARTVTK,
    ])


def binding_refs(owner_path: Path, definition: Path, source_request: Path, plan: Path) -> dict[str, Any]:
    return {
        "source_owner": ref(owner_path),
        "source_definition": ref(definition),
        "source_gencase_request": ref(source_request),
        "source_plan": ref(plan),
    }


def make_basic_binding(row: dict[str, Any], owner_path: Path, definition: Path, source_request: Path, plan: Path, gen_request: dict[str, Any], qa_request_path: Path) -> dict[str, Any]:
    case = row["case_id"]
    attempts_ = attempts(case, gen_request["attempt_id"])
    future = future_paths(case, gen_request["attempt_id"])
    owner = load_json(owner_path)
    return {
        "schema": "ds02.f4.fresh103.gencase-basic-input-binding.v1",
        "scope_id": "F4_STAGE1_FIRST48_FRESH102_PRE_SOLVER_GENCASE_BASIC_INITIAL_QA_V1",
        "family_id": "F4",
        "case_id": case,
        "physical_case_id": row["physical_case_id"],
        "physical_condition_sha256": row["physical_condition_sha256"],
        "source_plan_condition_sha256": row["source_plan_condition_sha256"],
        "source_only": True,
        "execution_allowed": False,
        "actual_source_commit": None,
        "request_path": str(qa_request_path),
        "worker_contract": {"path": str(FRESH095 / "workers/run_f4_fresh095_gencase_basic_initial_qa.py"), "sha256": sha(FRESH095 / "workers/run_f4_fresh095_gencase_basic_initial_qa.py")},
        **binding_refs(owner_path, definition, source_request, plan),
        "fresh102_source_gencase_request": ref(Path(gen_request["_fresh102_source_request_path"])),
        "actual_root604_gencase_request": {"path": str(source_request), "sha256": sha(source_request)},
        "gencase": {
            "request": ref(source_request),
            "attempt_id": gen_request["attempt_id"],
            "receipt": {"path": future["gencase_receipt"], "sha256": None, "status": None, "returncode": None},
            "generated_xml": {"path": future["generated_xml"], "sha256": None},
            "generated_bi4": {"path": future["generated_bi4"], "producer_sha256": None, "read_by_source": False},
            "prepared_report": {"path": future["prepared_report"], "sha256": None},
        },
        "expected": {
            "solver_dimension": 3,
            "data2d": False,
            "dp_m": DP,
            "total_particles": None,
            "fixed_particles": None,
            "moving_particles": None,
            "floating_particles": None,
            "fluid_particles": None,
            "density_kg_m3": 1000.0,
            "parameters": dict(row["parameters"]),
            "tank": owner["geometry"]["tank"],
            "sources": {
                "pool": owner["geometry"]["pool"],
                "drop": owner["geometry"]["drop"],
            },
            "source_bounds_and_clearance": source_geometry(owner, row),
        },
        "initial_velocity_declaration": {
            "values": owner["initial_state"]["velocities_m_per_s"],
            "claim": "source XML/GenCase declaration only; native frame-0 velocity is not observed here",
        },
        "reader": {
            "safe_decoder": {"path": str(DECODER), "registered_sha256": "affbbb6c04a4d21d03037e74d0023112c60c7d8e5972cc6dfc882e1c7c5dc319", "source_read_or_hashed": False},
            "partvtk_binary": {"path": str(PARTVTK_REGISTERED), "registered_sha256": "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e", "source_read_or_hashed": False},
            "registered_job_arrays": ["Posd", "Idp"],
            "raw_marker_arrays": {"Mk": "not_required/not_observed", "Type": "not_required/not_observed"},
        },
        "checks": {
            "actual_3d": None,
            "finite_positions": None,
            "unique_complete_initial_uid": None,
            "actual_counts": None,
            "source_uid_partition": None,
            "inclusive_xml_extrema": None,
            "drop_pool_nonoverlap": None,
            "tank_containment": None,
            "source_recipe_unchanged": None,
        },
        "mass_policy": {
            "native_vs_nominal_report": True,
            "mass_rescaled": False,
            "stage1_gate": False,
            "exact_continuum_lattice_gate": False,
            "old_pool_drop_continuum_and_dp_lattice_negative_preserved": True,
        },
        "future_hashes": {
            "gencase_receipt_sha256": None,
            "generated_xml_sha256": None,
            "generated_bi4_sha256": None,
            "prepared_report_sha256": None,
            "initial_qa_receipt_sha256": None,
            "initial_qa_report_sha256": None,
        },
        "claim_boundary": "Prospective source template only. Root must materialize actual GenCase metadata before enabling the Root502-compatible worker; no native solver/frame-0/typed/XMF/render/precision/Q-N/production claim.",
    }


def make_basic_request(row: dict[str, Any], owner_path: Path, definition: Path, source_request: Path, plan: Path, gen_request: dict[str, Any], binding_path: Path, request_path: Path) -> dict[str, Any]:
    case = row["case_id"]
    a = attempts(case, gen_request["attempt_id"])
    f = future_paths(case, gen_request["attempt_id"])
    worker = PACKAGE / "workers/run_fresh103_basic_initial_qa.py"
    static = base_static_for_case(case, definition, owner_path, source_request, plan) + [binding_path, worker, FRESH095 / "workers/run_f4_fresh095_gencase_basic_initial_qa.py"]
    static = unique(static)
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F4",
        "case_id": case,
        "physical_case_id": row["physical_case_id"],
        "physical_condition_sha256": row["physical_condition_sha256"],
        "attempt_id": a["basic_qa"],
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 4,
        "command": [str(PYTHON), str(worker), "--binding", str(binding_path), "--output", "{attempt_root}/gencase-basic-initial-qa.json"],
        "cwd": str(WORKTREE),
        "worktree_root": str(WORKTREE),
        "launch_owner": "root",
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "disabled": True,
        "jobs_started_by_source": False,
        "arrays_read_by_source": False,
        "status": "disabled_waiting_actual_gencase_metadata",
        "disabled_reason": "Materialize actual GenCase receipt/prepared-report/XML/BI4 producer attestation first; then the adapter delegates to the passed Root502-compatible basic QA worker. No native solver receipt is required for this pre-solver stage.",
        "depends_on_attempts": [a["gencase"]],
        "input_files": [str(p) for p in static],
        "input_sha256": {str(p): sha(p) for p in static},
        "deferred_input_files": [f["gencase_receipt"], f["generated_xml"], f["generated_bi4"], f["prepared_report"]],
        "deferred_input_sha256": {p: None for p in [f["gencase_receipt"], f["generated_xml"], f["generated_bi4"], f["prepared_report"]]},
        "expected": {
            "solver_dimension": 3,
            "data2d": False,
            "actual_counts_from_prepared_report": True,
            "total_particles_from_gencase": None,
            "fixed_particles_from_gencase": None,
            "moving_particles_from_gencase": None,
            "fluid_particles_from_gencase": None,
            "generated_xml_sha256": None,
            "generated_bi4_sha256": None,
            "initial_qa_report_sha256": None,
        },
        "output_contract": {
            "execution_receipt": "{attempt_root}/execution-receipt.json",
            "report": "{attempt_root}/gencase-basic-initial-qa.json",
            "resolved_binding": "{attempt_root}/resolved-fresh095-binding.json",
            "future_sha256": None,
        },
        "adapter_contract": {
            "materializes_actual_counts_only_from": ["prepared-input-report.json", "completed/0 GenCase receipt", "generated XML metadata"],
            "does_not_read_or_hash_source_bi4": True,
            "delegated_worker": str(FRESH095 / "workers/run_f4_fresh095_gencase_basic_initial_qa.py"),
            "native_frame0_velocity": "not available at this stage",
        },
        "recipe": recipe(),
        "precision_status": "not_accepted",
        "q_n_status": "not_granted",
        "production_approval": False,
        "independent_case_count_increment": 0,
        "root_review_required": True,
    }


def make_native_binding(row: dict[str, Any], owner_path: Path, definition: Path, source_request: Path, plan: Path, gen_request: dict[str, Any], basic_binding_path: Path, basic_request_path: Path, native_request_path: Path) -> dict[str, Any]:
    case = row["case_id"]
    a = attempts(case, gen_request["attempt_id"])
    f = future_paths(case, gen_request["attempt_id"])
    owner = load_json(owner_path)
    return {
        "schema": "ds02.f4.fresh103.native-input-binding.v1",
        "scope_id": "F4_STAGE1_FIRST48_ROOT230_FULL1201_NATIVE_V1",
        "family_id": "F4",
        "case_id": case,
        "physical_case_id": row["physical_case_id"],
        "physical_condition_sha256": row["physical_condition_sha256"],
        "source_plan_condition_sha256": row["source_plan_condition_sha256"],
        "source_only": True,
        "execution_allowed": False,
        "request_path": str(native_request_path),
        **binding_refs(owner_path, definition, source_request, plan),
        "fresh102_source_gencase_request": ref(Path(gen_request["_fresh102_source_request_path"])),
        "actual_root604_gencase_request": {"path": str(source_request), "sha256": sha(source_request)},
        "source_gencase": {
            "request": ref(source_request),
            "attempt_id": a["gencase"],
            "generated_xml": {"path": f["generated_xml"], "sha256": None},
            "generated_bi4": {"path": f["generated_bi4"], "producer_sha256": None, "read_by_source": False},
            "prepared_report": {"path": f["prepared_report"], "sha256": None},
            "receipt": {"path": f["gencase_receipt"], "sha256": None, "status": None, "returncode": None},
        },
        "basic_qa_gate": {
            "request": {"path": str(basic_request_path), "sha256": None},
            "binding": {"path": str(basic_binding_path), "sha256": None},
            "attempt_id": a["basic_qa"],
            "status": "future_completed0_required",
            "report_sha256": None,
            "pass": None,
        },
        "expected": {
            "solver_dimension": 3,
            "data2d": False,
            "total_particles": None,
            "fixed_particles": None,
            "moving_particles": None,
            "floating_particles": None,
            "fluid_particles": None,
            "native_frame_count": FRAMES,
            "native_frame0_counts": None,
        },
        "recipe": recipe(),
        "native_solver": {
            "attempt_id": a["native"],
            "receipt": {"path": str(DATA_ROOT / case / a["native"] / "execution-receipt.json"), "sha256": None, "status": None, "returncode": None},
            "output_root": str(DATA_ROOT / case / a["native"]),
            "data_root": str(DATA_ROOT / case / a["native"] / "solver_output/data"),
            "frame0_bi4": str(DATA_ROOT / case / a["native"] / "solver_output/data/Part_0000.bi4"),
            "status": "WAIT",
        },
        "root230": {
            "profile": "root_live_all_idle_uuid_leased_eight_solver_v2",
            "uuid_selection": "Root resolves live non-foreign UUID at enable time",
            "foreign_gpu_protection": True,
            "home_free_gib_floor": 500,
            "nvme_free_gib_floor": 100,
            "nvme_peak_gib": 24,
            "concurrency_cap": 8,
            "estimated_storage_bytes": 64 * 1024**3,
            "storage_estimate_requires_actual_count_recompute": True,
        },
        "frame0_gate": {
            "status": "future_native_frame0_audit_required",
            "request": None,
            "report_sha256": None,
            "native_raw_mk_type": None,
            "native_raw_velocity": None,
        },
        "mass_policy": {
            "native_vs_nominal_report": True,
            "mass_rescaled": False,
            "continuum_volume_gate": False,
            "dp_lattice_gate": False,
        },
        "future_hashes": {"native_receipt_sha256": None, "solver_output_sha256": None, "frame0_report_sha256": None},
        "claim_boundary": "Native solver remains disabled until this case has actual GenCase and basic QA completed/0. Source GenCase placement and XML velocity do not prove native frame-0 marker or velocity behavior.",
    }


def make_native_request(row: dict[str, Any], owner_path: Path, definition: Path, source_request: Path, plan: Path, gen_request: dict[str, Any], basic_binding_path: Path, basic_request_path: Path, native_binding_path: Path, native_request_path: Path) -> dict[str, Any]:
    case = row["case_id"]
    a = attempts(case, gen_request["attempt_id"])
    f = future_paths(case, gen_request["attempt_id"])
    owner = load_json(owner_path)
    static = base_static_for_case(case, definition, owner_path, source_request, plan) + [basic_binding_path, basic_request_path, native_binding_path, PACKAGE / "workers/run_fresh103_basic_initial_qa.py"]
    static = unique(static)
    worker = str(SOLVER)
    prefix = str(Path(f["generated_xml"]).with_suffix(""))
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F4",
        "case_id": case,
        "physical_case_id": row["physical_case_id"],
        "physical_condition_sha256": row["physical_condition_sha256"],
        "attempt_id": a["native"],
        "kind": "gpu",
        "cpu_task_kind": "native_solver",
        "cpu_threads": 2,
        "omp_threads": 2,
        "command": [worker, prefix, "{attempt_root}/solver_output", "-tmax:1.2", "-tout:0.001"],
        "cwd": str(Path(f["generated_xml"]).parent),
        "worktree_root": str(WORKTREE),
        "launch_owner": "root",
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "disabled": True,
        "jobs_started_by_source": False,
        "arrays_read_by_source": False,
        "status": "disabled_waiting_basic_qa_completed0",
        "disabled_reason": "Enable only after the matching actual GenCase receipt and Root502-compatible basic QA report are completed/0 and passed. Root230 must resolve the live UUID and preserve foreign-process/Home/NVMe guards.",
        "depends_on_attempts": [a["gencase"], a["basic_qa"]],
        "input_files": [str(p) for p in static],
        "input_sha256": {str(p): sha(p) for p in static},
        "deferred_input_files": [f["gencase_receipt"], f["generated_xml"], f["generated_bi4"], f["prepared_report"], str(DATA_ROOT / case / a["basic_qa"] / "execution-receipt.json"), str(DATA_ROOT / case / a["basic_qa"] / "gencase-basic-initial-qa.json")],
        "deferred_input_sha256": {p: None for p in [f["gencase_receipt"], f["generated_xml"], f["generated_bi4"], f["prepared_report"], str(DATA_ROOT / case / a["basic_qa"] / "execution-receipt.json"), str(DATA_ROOT / case / a["basic_qa"] / "gencase-basic-initial-qa.json")]},
        "expected": {
            "solver_dimension": 3,
            "data2d": False,
            "actual_counts_from_basic_qa": True,
            "total_particles": None,
            "fixed_particles": None,
            "moving_particles": None,
            "fluid_particles": None,
            "native_frame_count": FRAMES,
            "native_receipt_sha256": None,
            "frame0_report_sha256": None,
        },
        "recipe": recipe(),
        "root230_policy": {
            "profile": "root_live_all_idle_uuid_leased_eight_solver_v2",
            "foreign_gpu_protection": True,
            "home_free_gib_floor": 500,
            "nvme_free_gib_floor": 100,
            "nvme_peak_gib": 24,
            "solver_concurrency_cap": 8,
            "uuid_selected_at_enablement": True,
        },
        "estimated_peak_gpu_mib": 8192,
        "estimated_storage_bytes": 64 * 1024**3,
        "estimated_storage_requires_actual_count_recompute": True,
        "outputs": {
            "execution_receipt": "{attempt_root}/execution-receipt.json",
            "data_root": "{attempt_root}/solver_output/data",
            "frame0_bi4": "{attempt_root}/solver_output/data/Part_0000.bi4",
            "full_native_frames": FRAMES,
            "native_frame0_audit": None,
            "typed_receipt": None,
            "all_future_sha256": None,
        },
        "frame0_gate": {
            "worker": str(PACKAGE / "workers/run_fresh103_frame0_audit.py"),
            "status": "future_after_native_completed0",
            "raw_mk_type_required": True,
            "raw_velocity_required": True,
        },
        "precision_status": "not_accepted",
        "q_n_status": "not_granted",
        "production_approval": False,
        "independent_case_count_increment": 0,
        "root_review_required": True,
    }


def make_frame_binding(row: dict[str, Any], owner_path: Path, definition: Path, source_request: Path, plan: Path, gen_request: dict[str, Any], native_binding_path: Path, native_request_path: Path, frame_request_path: Path) -> dict[str, Any]:
    case = row["case_id"]
    a = attempts(case, gen_request["attempt_id"])
    f = future_paths(case, gen_request["attempt_id"])
    owner = load_json(owner_path)
    native_root = DATA_ROOT / case / a["native"]
    case_payload = {
        "case_id": case,
        "physical_case_id": row["physical_case_id"],
        "physical_condition_sha256": row["physical_condition_sha256"],
        "native_solver_status": "WAIT",
        "native_solver_receipt": str(native_root / "execution-receipt.json"),
        "native_solver_receipt_sha256": None,
        "native_output_root": str(native_root),
        "native_data_dir": str(native_root / "solver_output/data"),
        "native_frame0_bi4": str(native_root / "solver_output/data/Part_0000.bi4"),
        "generated_xml": f["generated_xml"],
        "generated_xml_sha256": None,
        "prepared_input_report": f["prepared_report"],
        "gencase_receipt": f["gencase_receipt"],
        "gencase_receipt_sha256": None,
        "actual_particle_counts": None,
        "actual_total_particles": None,
        "expected_native_types": recipe()["native_types"],
        "expected_velocity_by_mk": None,
        "declared_velocity_by_mkfluid": owner["initial_state"]["velocities_m_per_s"],
        "historical_root530_marker_map": {"mkfluid:0": "Mk:1", "mkfluid:1": "Mk:2"},
        "velocity_tolerance_m_per_s": 1e-6,
        "partvtk": str(PARTVTK),
        "partvtk_sha256": None,
        "raw_marker_mapping_source": "future actual PartVTK report; historical Root530 map is informational only",
    }
    return {
        "schema": "ds02.f4.fresh103.native-frame0-input-binding.v1",
        "scope_id": "F4_STAGE1_FIRST48_ROOT530_NATIVE_FRAME0_AUDIT_V1",
        "family_id": "F4",
        "case_id": case,
        "physical_case_id": row["physical_case_id"],
        "physical_condition_sha256": row["physical_condition_sha256"],
        "source_only": True,
        "execution_allowed": False,
        "request_path": str(frame_request_path),
        "worker_contract": {"path": str(FRESH097 / "workers/native_frame0_partvtk_vz_audit.py"), "sha256": sha(FRESH097 / "workers/native_frame0_partvtk_vz_audit.py")},
        "source_owner": ref(owner_path),
        "source_definition": ref(definition),
        "source_gencase_request": ref(source_request),
        "source_plan": ref(plan),
        "fresh102_source_gencase_request": ref(Path(gen_request["_fresh102_source_request_path"])),
        "actual_root604_gencase_request": {"path": str(source_request), "sha256": sha(source_request)},
        "native_binding": {"path": str(native_binding_path), "sha256": None},
        "native_request": {"path": str(native_request_path), "sha256": None},
        "root530_worker_contract": ref(FRESH097 / "metadata/fresh097-stage-contract.json"),
        "cases": [case_payload],
        "native_solver_status": "WAIT",
        "expected_native_types": recipe()["native_types"],
        "raw_mk_type_required": True,
        "raw_velocity_required": True,
        "gencase_declared_velocity_is_not_native_evidence": True,
        "no_padding_or_forced_counts": True,
        "future_report": None,
        "future_report_sha256": None,
        "future_hashes": {"native_receipt_sha256": None, "frame0_bi4_sha256": None, "audit_report_sha256": None},
        "claim_boundary": "Post-native frame-0 template only. Root must materialize actual native receipt, GenCase metadata, raw-marker map and PartVTK input before enabling the Root530-compatible worker.",
    }


def make_frame_request(row: dict[str, Any], owner_path: Path, definition: Path, source_request: Path, plan: Path, gen_request: dict[str, Any], native_binding_path: Path, native_request_path: Path, frame_binding_path: Path, frame_request_path: Path) -> dict[str, Any]:
    case = row["case_id"]
    a = attempts(case, gen_request["attempt_id"])
    f = future_paths(case, gen_request["attempt_id"])
    static = base_static_for_case(case, definition, owner_path, source_request, plan) + [native_binding_path, native_request_path, frame_binding_path, PACKAGE / "workers/run_fresh103_frame0_audit.py"]
    static = unique(static)
    worker = PACKAGE / "workers/run_fresh103_frame0_audit.py"
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F4",
        "case_id": case,
        "physical_case_id": row["physical_case_id"],
        "physical_condition_sha256": row["physical_condition_sha256"],
        "attempt_id": a["frame0"],
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 4,
        "command": [str(PYTHON), str(worker), "--binding", str(frame_binding_path), "--output-dir", "{attempt_root}/audit"],
        "cwd": str(WORKTREE),
        "worktree_root": str(WORKTREE),
        "launch_owner": "root",
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "disabled": True,
        "jobs_started_by_source": False,
        "arrays_read_by_source": False,
        "status": "disabled_waiting_native_completed0",
        "disabled_reason": "Enable only after matching Root230 native completed/0 and actual GenCase/basic-QA metadata. The wrapper resolves actual counts and the raw-Mk velocity map, then delegates to the passed Root530 official PartVTK worker.",
        "depends_on_attempts": [a["native"]],
        "input_files": [str(p) for p in static],
        "input_sha256": {str(p): sha(p) for p in static},
        "deferred_input_files": [str(DATA_ROOT / case / a["native"] / "execution-receipt.json"), str(DATA_ROOT / case / a["native"] / "solver_output/data/Part_0000.bi4"), f["generated_xml"], f["prepared_report"], f["gencase_receipt"]],
        "deferred_input_sha256": {p: None for p in [str(DATA_ROOT / case / a["native"] / "execution-receipt.json"), str(DATA_ROOT / case / a["native"] / "solver_output/data/Part_0000.bi4"), f["generated_xml"], f["prepared_report"], f["gencase_receipt"]]},
        "expected": {
            "native_receipt_status": "completed/0 required",
            "native_frame_count": FRAMES,
            "actual_total_particles_from_basic_qa": None,
            "actual_fluid_particles_from_basic_qa": None,
            "native_frame0_particles": None,
            "native_frame0_fluid_particles": None,
            "raw_mk_type_observed": None,
            "raw_velocity_observed": None,
            "audit_report_sha256": None,
        },
        "adapter_contract": {
            "materializes_actual_counts_from": "completed basic-QA report / prepared XML metadata",
            "materializes_native_status_from": "matching Root230 receipt JSON",
            "marker_map": "historical Root530 map is fallback metadata only; actual PartVTK raw Mk must be observed and checked",
            "delegated_worker": str(FRESH097 / "workers/native_frame0_partvtk_vz_audit.py"),
            "scientific_payload_read": "only the Root-registered official PartVTK worker reads native BI4/CSV after enablement",
        },
        "recipe": recipe(),
        "estimated_storage_bytes": 2 * 1024**3,
        "root_review_required": True,
    }


def copy_wrapper_sources() -> None:
    (PACKAGE / "workers").mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).resolve(), PACKAGE / "workers/build_fresh103.py")
    # The two wrappers are emitted below from stable templates in this builder.


def write_wrappers() -> None:
    basic = r'''#!/usr/bin/env python3
"""Materialize a fresh103 template from actual GenCase metadata, then reuse fresh095."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, shutil
from pathlib import Path
import xml.etree.ElementTree as ET
HEX=set("0123456789abcdef")

def load(p):
    v=json.loads(Path(p).read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise RuntimeError(f"metadata object required: {p}")
    return v

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def valid(v): return isinstance(v,str) and len(v)==64 and set(v.lower())<=HEX

def first_int(items, label):
    for v in items:
        if v is not None:
            try:
                n=int(v)
            except (TypeError,ValueError):
                continue
            if n>0: return n
    raise RuntimeError(f"actual {label} is missing from registered metadata")

def counts(report, receipt):
    blocks=report.get("generated_xml_particle_counts") or report.get("particle_counts") or {}
    total=first_int([report.get("actual_total_particles"), report.get("total_particles"), blocks.get("total"), blocks.get("np"), receipt.get("total_particles")],"total_particles")
    fixed=first_int([blocks.get("fixed"), blocks.get("nb"), report.get("fixed_particles"), receipt.get("fixed_particles")],"fixed_particles")
    fluid=first_int([blocks.get("fluid"), blocks.get("nfluid"), report.get("fluid_particles"), receipt.get("fluid_particles")],"fluid_particles")
    moving=int(blocks.get("moving", report.get("moving_particles", receipt.get("moving_particles", 0))) or 0)
    floating=int(blocks.get("floating", report.get("floating_particles", receipt.get("floating_particles", 0))) or 0)
    if total != fixed+fluid+moving+floating: raise RuntimeError("actual GenCase counts do not close")
    return {"total":total,"fixed":fixed,"fluid":fluid,"moving":moving,"floating":floating}

def bi4_producer(report, receipt):
    candidates=[]
    for d in (report,receipt):
        for key in ("generated_bi4_sha256","bi4_sha256","producer_sha256"):
            candidates.append(d.get(key))
        for key in ("generated_bi4","bi4"):
            x=d.get(key)
            if isinstance(x,dict): candidates.append(x.get("producer_sha256") or x.get("sha256"))
    for x in candidates:
        if valid(x): return x
    raise RuntimeError("GenCase BI4 producer attestation missing; wrapper never hashes BI4")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--binding",required=True,type=Path); ap.add_argument("--output",required=True,type=Path); a=ap.parse_args()
    template=load(a.binding)
    if template.get("schema")!="ds02.f4.fresh103.gencase-basic-input-binding.v1": raise RuntimeError("fresh103 binding schema mismatch")
    g=template["gencase"]
    receipt_path=Path(g["receipt"]["path"]); report_path=Path(g["prepared_report"]["path"]); xml_path=Path(g["generated_xml"]["path"])
    receipt=load(receipt_path); report=load(report_path)
    if receipt.get("status") not in {"completed","completed/0"} or receipt.get("returncode")!=0: raise RuntimeError("GenCase receipt is not completed/0")
    if receipt.get("solver_dimension_from_gencase") not in {3,"3"}: raise RuntimeError("GenCase receipt is not 3-D")
    c=counts(report,receipt)
    xml_root=ET.parse(xml_path).getroot(); d2=xml_root.find(".//execution/constants/data2d")
    if d2 is None: d2=xml_root.find(".//data2d")
    if d2 is None or str(d2.attrib.get("value","")).lower()!="false": raise RuntimeError("generated XML is not explicit 3-D")
    runtime=json.loads(json.dumps(template))
    runtime["expected"].update({"total_particles":c["total"],"fixed_particles":c["fixed"],"fluid_particles":c["fluid"],"moving_particles":c["moving"],"floating_particles":c["floating"]})
    runtime["gencase"]["receipt"].update({"sha256":sha(receipt_path),"status":receipt.get("status"),"returncode":receipt.get("returncode")})
    runtime["gencase"]["prepared_report"]["sha256"]=sha(report_path)
    runtime["gencase"]["generated_xml"]["sha256"]=sha(xml_path)
    runtime["gencase"]["generated_bi4"]["producer_sha256"]=bi4_producer(report,receipt)
    runtime["materialized_from_actual_metadata"]=True
    resolved=a.output.parent/"resolved-fresh095-binding.json"; resolved.write_text(json.dumps(runtime,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    worker=Path(template["worker_contract"]["path"])
    spec=importlib.util.spec_from_file_location("fresh095_worker",worker); mod=importlib.util.module_from_spec(spec); assert spec.loader
    spec.loader.exec_module(mod)
    ns=argparse.Namespace(binding=resolved,output=a.output)
    raise SystemExit(mod.run(ns))
if __name__=="__main__": main()
'''
    frame = r'''#!/usr/bin/env python3
"""Materialize a fresh103 frame-0 template from actual metadata, then reuse fresh097."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json
from pathlib import Path
import xml.etree.ElementTree as ET
HEX=set("0123456789abcdef")

def load(p):
    v=json.loads(Path(p).read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise RuntimeError(f"metadata object required: {p}")
    return v

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def valid(v): return isinstance(v,str) and len(v)==64 and set(v.lower())<=HEX

def marker_map(template):
    # This is only the historical Root530 observation; the registered worker
    # still observes raw Mk and fails if the actual map/velocity rows disagree.
    m=template.get("historical_root530_marker_map") or {"mkfluid:0":"Mk:1","mkfluid:1":"Mk:2"}
    out={}
    for source,raw in m.items():
        if not isinstance(raw,str) or not raw.startswith("Mk:"): raise RuntimeError("invalid marker map")
        out["mk:"+raw.split(":",1)[1]]=template["declared_velocity_by_mkfluid"][source]
    return out

def actual_counts(report):
    audit=report.get("audit",{})
    root=audit.get("root_values",{})
    blocks=report.get("generated_xml_particle_counts") or report.get("particle_counts") or {}
    def pick(*vals):
        for v in vals:
            if v is not None:
                try: return int(v)
                except (TypeError,ValueError): pass
        raise RuntimeError("actual GenCase count missing in basic QA metadata")
    total=pick(root.get("CaseNp"),report.get("actual_total_particles"),blocks.get("total"))
    fixed=pick(root.get("CaseNfixed"),blocks.get("fixed"),report.get("fixed_particles"))
    fluid=pick(root.get("CaseNfluid"),blocks.get("fluid"),report.get("fluid_particles"))
    return {"fixed":fixed,"moving":int(blocks.get("moving",report.get("moving_particles",0)) or 0),"floating":int(blocks.get("floating",report.get("floating_particles",0)) or 0),"fluid":fluid},total

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--binding",required=True,type=Path); ap.add_argument("--output-dir",required=True,type=Path); a=ap.parse_args()
    template=load(a.binding)
    if template.get("schema")!="ds02.f4.fresh103.native-frame0-input-binding.v1": raise RuntimeError("fresh103 frame binding schema mismatch")
    case=template["cases"][0]; receipt_path=Path(case["native_solver_receipt"]); require=receipt_path.is_file()
    if not require: raise RuntimeError("native receipt missing")
    receipt=load(receipt_path)
    if receipt.get("status") not in {"completed","completed/0"} or receipt.get("returncode")!=0: raise RuntimeError("native receipt is not completed/0")
    report_path=Path(case["prepared_input_report"]); report=load(report_path)
    counts,total=actual_counts(report)
    xml_path=Path(case["generated_xml"]); xml_root=ET.parse(xml_path).getroot(); d2=xml_root.find(".//execution/constants/data2d")
    if d2 is None: d2=xml_root.find(".//data2d")
    if d2 is None or str(d2.attrib.get("value","")).lower()!="false": raise RuntimeError("generated XML is not explicit 3-D")
    runtime=json.loads(json.dumps(template)); rc=runtime["cases"][0]
    output_root=Path(receipt.get("output_root") or rc["native_output_root"]); data_root=output_root/"solver_output/data"
    rc["native_solver_status"]="completed/0"; rc["native_solver_receipt_sha256"]=sha(receipt_path); rc["native_output_root"]=str(output_root); rc["native_data_dir"]=str(data_root); rc["native_frame0_bi4"]=str(data_root/"Part_0000.bi4")
    rc["generated_xml_sha256"]=sha(xml_path); rc["gencase_receipt_sha256"]=sha(Path(rc["gencase_receipt"]))
    rc["actual_particle_counts"]=counts; rc["actual_total_particles"]=total; rc["expected_velocity_by_mk"]=marker_map(rc); rc["partvtk_sha256"]=None
    runtime["native_solver_status"]="completed/0"; runtime["future_report_sha256"]=None; runtime["materialized_from_actual_metadata"]=True
    resolved=a.output_dir/"resolved-fresh097-binding.json"; resolved.parent.mkdir(parents=True,exist_ok=True); resolved.write_text(json.dumps(runtime,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    worker=Path(template["worker_contract"]["path"])
    spec=importlib.util.spec_from_file_location("fresh097_worker",worker); mod=importlib.util.module_from_spec(spec); assert spec.loader
    spec.loader.exec_module(mod)
    ns=argparse.Namespace(binding=resolved,output_dir=a.output_dir)
    # Call the worker's public audit loop without reconstructing scientific parsing.
    results=[mod.audit(c,a.output_dir) for c in runtime["cases"]]
    out=a.output_dir/"native-frame0-partvtk-vz-audit.json"
    out.write_text(json.dumps({"schema":"ds02.f4.fresh103.native-frame0-partvtk-vz-audit.v1","source_only_worker":True,"native_frame0_source":"official PartVTK on solver-saved Part_0000.bi4","raw_mk_type_observed":True,"raw_velocity_observed":True,"gencase_raw_velocity_claim":"not_used","mass_rescaling":False,"cases":results,"q_n":"not_assessed","production_approval":"none","independent_case_count_increment":0},indent=2,sort_keys=True)+"\n",encoding="utf-8")
if __name__=="__main__": main()
'''
    (PACKAGE / "workers/run_fresh103_basic_initial_qa.py").write_text(basic, encoding="utf-8")
    (PACKAGE / "workers/run_fresh103_frame0_audit.py").write_text(frame, encoding="utf-8")
    for path in (PACKAGE / "workers/run_fresh103_basic_initial_qa.py", PACKAGE / "workers/run_fresh103_frame0_audit.py"):
        path.chmod(0o755)


def build() -> None:
    # Rebuild only this fresh package.  The source task never touches other family data.
    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    (PACKAGE / "bindings").mkdir(parents=True)
    (PACKAGE / "requests").mkdir(parents=True)
    (PACKAGE / "metadata").mkdir(parents=True)
    (PACKAGE / "workers").mkdir(parents=True)
    (PACKAGE / "tests").mkdir(parents=True)
    write_upstream_metadata()
    write_wrappers()
    plan = load_json(FRESH102 / "source-plan.json")
    rows = sorted(plan["rows"], key=lambda r: int(r["rank"]))
    if len(rows) != 24 or len({r["case_id"] for r in rows}) != 24:
        raise ValueError("fresh102 must provide 24 unique rows")
    records: list[dict[str, Any]] = []
    for row in rows:
        case = row["case_id"]
        definition, owner_path, source_request, plan_path, owner, gen_request = source_refs(row)
        gen_attempt = gen_request["attempt_id"]
        basic_binding_path = PACKAGE / "bindings" / f"{case}.gencase-basic-input-binding.json"
        basic_request_path = PACKAGE / "requests" / f"{case}.gencase-basic-initial-qa-103-disabled.request.json"
        native_binding_path = PACKAGE / "bindings" / f"{case}.native-input-binding.json"
        native_request_path = PACKAGE / "requests" / f"{case}.full1201-native-root230-103-disabled.request.json"
        frame_binding_path = PACKAGE / "bindings" / f"{case}.native-frame0-input-binding.json"
        frame_request_path = PACKAGE / "requests" / f"{case}.native-frame0-partvtk-vz-103-disabled.request.json"
        dump(basic_binding_path, make_basic_binding(row, owner_path, definition, source_request, plan_path, gen_request, basic_request_path))
        dump(native_binding_path, make_native_binding(row, owner_path, definition, source_request, plan_path, gen_request, basic_binding_path, basic_request_path, native_request_path))
        dump(frame_binding_path, make_frame_binding(row, owner_path, definition, source_request, plan_path, gen_request, native_binding_path, native_request_path, frame_request_path))
        # Requests are generated after bindings so their input hashes close over final binding bytes.
        dump(basic_request_path, make_basic_request(row, owner_path, definition, source_request, plan_path, gen_request, basic_binding_path, basic_request_path))
        native_binding = load_json(native_binding_path)
        native_binding["basic_qa_gate"]["request"]["sha256"] = sha(basic_request_path)
        native_binding["basic_qa_gate"]["binding"]["sha256"] = sha(basic_binding_path)
        dump(native_binding_path, native_binding)
        dump(native_request_path, make_native_request(row, owner_path, definition, source_request, plan_path, gen_request, basic_binding_path, basic_request_path, native_binding_path, native_request_path))
        frame_binding = load_json(frame_binding_path)
        frame_binding["native_binding"]["sha256"] = sha(native_binding_path)
        frame_binding["native_request"]["sha256"] = sha(native_request_path)
        dump(frame_binding_path, frame_binding)
        dump(frame_request_path, make_frame_request(row, owner_path, definition, source_request, plan_path, gen_request, native_binding_path, native_request_path, frame_binding_path, frame_request_path))
        records.extend([
            {"kind": "gencase-basic-initial-qa", "case_id": case, "path": str(basic_request_path), "sha256": sha(basic_request_path), "disabled": True},
            {"kind": "full1201-native-root230", "case_id": case, "path": str(native_request_path), "sha256": sha(native_request_path), "disabled": True},
            {"kind": "native-frame0-partvtk-vz", "case_id": case, "path": str(frame_request_path), "sha256": sha(frame_request_path), "disabled": True},
        ])
    # Recompute request hashes only after binding updates.  Binding files are inputs to requests;
    # the request content itself remains unchanged, so no self-cycle exists.
    records = []
    for row in rows:
        case = row["case_id"]
        for kind, filename in [
            ("gencase-basic-initial-qa", f"{case}.gencase-basic-initial-qa-103-disabled.request.json"),
            ("full1201-native-root230", f"{case}.full1201-native-root230-103-disabled.request.json"),
            ("native-frame0-partvtk-vz", f"{case}.native-frame0-partvtk-vz-103-disabled.request.json"),
        ]:
            p = PACKAGE / "requests" / filename
            records.append({"kind": kind, "case_id": case, "path": str(p), "sha256": sha(p), "disabled": True})
    dump(PACKAGE / "requests/index.json", {"schema": "ds02.f4.fresh103.request-index.v1", "case_count": 24, "request_count": 72, "launch_allowed": False, "all_disabled": True, "rows": records})
    # Evidence closure deliberately excludes generated native payloads.  It includes only metadata/code inputs.
    static_paths = source_static_paths()
    for row in rows:
        definition, owner_path, source_request, plan_path, _, _ = source_refs(row)
        static_paths.extend([definition, owner_path, source_request, FRESH102 / "requests" / f"{row['case_id']}-gencase.request.json", ROOT604 / f"{row['case_id']}-gencase-binding.json", plan_path])
    static_paths.extend([
        PACKAGE / "metadata/fresh103-stage-contract.json",
        PACKAGE / "metadata/fresh103-marker-semantics.json",
        PACKAGE / "metadata/fresh103-upstream-contracts.json",
        PACKAGE / "metadata/fresh103-gencase-basic-contract.json",
        PACKAGE / "metadata/fresh103-native-contract.json",
        PACKAGE / "metadata/fresh103-native-frame0-contract.json",
        PACKAGE / "workers/run_fresh103_basic_initial_qa.py",
        PACKAGE / "workers/run_fresh103_frame0_audit.py",
    ])
    static_paths = unique(static_paths)
    dump(PACKAGE / "evidence/source-static-closure.json", {
        "schema": "ds02.f4.fresh103.source-static-closure.v1",
        "source_only": True,
        "scientific_payloads_read_or_hashed": [],
        "allowed_suffixes": sorted(STATIC_SUFFIXES),
        "files": [ref(path) for path in static_paths],
        "future_payloads": "generated BI4/XML/report, native BI4, PartVTK CSV, H5, typed/XMF/render outputs are deferred and all hashes remain null",
    })
    manifest = {
        "schema": "ds02.f4.fresh103.manifest.v1",
        "family_id": "F4",
        "scope_id": "F4_STAGE1_FIRST48_FRESH102_GCASE_TO_NATIVE_FRAME0_V1",
        "source_only": True,
        "case_count": 24,
        "disabled_request_count": 72,
        "future_hashes_null": True,
        "upstream": {"fresh102": ref(FRESH102 / "source-plan.json"), "fresh095": ref(FRESH095 / "metadata/fresh095-stage1-contract.json"), "fresh097": ref(FRESH097 / "metadata/fresh097-stage-contract.json"), "root604": ref(ROOT604 / "actual-root-disjoint24-genuineGenCase-enable-review.json"), "root605": ref(ROOT605 / "controller-result.json")},
        "request_index": ref(PACKAGE / "requests/index.json"),
        "static_closure": ref(PACKAGE / "evidence/source-static-closure.json"),
        "claim_boundary": "No actual GenCase, QA, native, frame-0, typed, XMF, render, precision, Q-N or production result is claimed by this source package.",
    }
    dump(PACKAGE / "manifest.json", manifest)
    readme = f'''# F4 fresh103 GenCase to native initial-QA source handoff

This package covers the 24 new fresh102 finite drop/pool definitions. It provides 24 disabled three-stage request chains:

1. **GenCase basic initial QA** materializes the actual prepared report and delegates to the reviewed Root502-compatible worker. It checks genuine 3-D, finite and unique initial IDs, source partition, XML inclusive drawbox extrema, pool/drop separation and tank containment.
2. **Root230 native** runs only after that case's actual basic QA report is completed/0 and passed. The recipe stays DP={DP:g}, 1.2 s, 0.001 s output interval, {FRAMES} frames, no forcing and no mDBC.
3. **Native frame-0 PartVTK QA** materializes the matching native receipt/count metadata and delegates to the reviewed Root530-compatible official PartVTK worker. It observes raw Mk/Type/Idp and saved velocity rows; it never treats the GenCase XML velocity declaration as solver evidence.

All future particle counts, producer attestations, receipts and output hashes are null. The source templates do not assert any historical particle count. The old continuum-volume and DP-lattice diagnostics remain diagnostic negatives only; no mass rescaling or Q-N/precision grant is made.

The source builder and validator hash only JSON/XML/Python/text metadata and approved executable inputs. BI4/H5/VTK/CSV/DAT payloads are deferred to Root-owned registered jobs. Root must materialize actual GenCase metadata before enabling a request and resolve the live Root230 UUID lease while protecting foreign processes.
'''
    (PACKAGE / "README.md").write_text(readme, encoding="utf-8")
    # Copy this builder last, then include its digest in the manifest only through the closure on later validation.
    shutil.copy2(Path(__file__).resolve(), PACKAGE / "workers/build_fresh103.py")
    (PACKAGE / "workers/build_fresh103.py").chmod(0o755)


if __name__ == "__main__":
    build()
