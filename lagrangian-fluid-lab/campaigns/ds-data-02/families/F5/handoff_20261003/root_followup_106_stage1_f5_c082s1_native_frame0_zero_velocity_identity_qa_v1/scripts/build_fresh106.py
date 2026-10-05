#!/usr/bin/env python3
"""Build the F5 fresh106 source-only native frame-0 QA package.

Only JSON, XML, Python, Markdown and text metadata are opened or hashed by
this builder.  Native BI4, solver data, CSV, H5, VTK and motion DAT files are
recorded as Root-bound future inputs and are never opened or hashed here.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


PKG = Path(__file__).resolve().parents[1]
F5_TREE = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA_CASE = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")
SOURCE105 = F5_TREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_105_stage1_f5_c082s1_short_native_typed_xmf_bed_disabled_v1"
SHORT_ROOT = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actualQA441_Gen426_two_short51_native_455"
ROOT230 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230"
RESOURCES = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
LAB = INTEGRATION / "lagrangian-fluid-lab"
PYTHON = LAB / ".venv/bin/python"
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
WORKER = PKG / "workers/native_frame0_zero_velocity_identity_audit.py"
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
ROOT230_POLICY_SHA = "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5"
ROOT230_LAUNCH_SHA = "7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e"
PARTVTK_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
ROOT142_POLICY_SHA = "2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5"
HASHABLE_SUFFIXES = {".json", ".py", ".xml", ".md", ".txt", ".log"}
SCIENCE_SUFFIXES = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npy", ".npz", ".dat"}

CANDIDATES = {
    "A080": {
        "native_request": SHORT_ROOT / "C082S1_MOTION_A080-native-request.json",
        "physical_source": SOURCE105 / "bindings/A080-physical-binding.json",
        "definition_source": SOURCE105 / "inputs/A080-Definition.xml",
        "owner_source": SOURCE105 / "inputs/A080-owner.json",
        "condition_id": "F5_RUNUP_DP020_C082S1_MOTION_A080_099",
        "qa_attempt": "root-stage1-f5-c082s1-A080-native-frame0-zero-velocity-qa-106",
    },
    "A120": {
        "native_request": SHORT_ROOT / "C082S1_MOTION_A120-native-request.json",
        "physical_source": SOURCE105 / "bindings/A120-physical-binding.json",
        "definition_source": SOURCE105 / "inputs/A120-Definition.xml",
        "owner_source": SOURCE105 / "inputs/A120-owner.json",
        "condition_id": "F5_RUNUP_DP020_C082S1_MOTION_A120_099",
        "qa_attempt": "root-stage1-f5-c082s1-A120-native-frame0-zero-velocity-qa-106",
    },
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.suffix.lower() == ".json", f"JSON metadata required: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha(path: Path) -> str:
    require(path.suffix.lower() in HASHABLE_SUFFIXES, f"source builder cannot hash science payload: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_source(src: Path, dst: Path) -> str:
    require(src.is_file(), f"source input missing: {src}")
    require(src.suffix.lower() in HASHABLE_SUFFIXES, f"source copy is not metadata: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return sha(dst)


def xml_metadata(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    require(root.tag == "case", f"generated XML root is not <case>: {path}")
    data2d = root.find("./execution/constants/data2d")
    require(data2d is not None and str(data2d.get("value", "")).lower() == "false",
            f"generated XML is not 3-D: {path}")
    particles = root.find("./execution/particles")
    counts: dict[str, int] = {}
    if particles is not None:
        for name in ("fixed", "moving", "floating", "fluid"):
            counts[name] = sum(int(node.get("count", "-1")) for node in particles.findall(name))
    return {"data2d": False, "xml_particle_counts": counts}


def check_native(candidate: str, spec: dict[str, Any]) -> dict[str, Any]:
    request_path = spec["native_request"]
    request = load_json(request_path)
    require(request.get("schema") == "ds02.runner-request.v2", f"{candidate}: native request schema")
    require(request.get("kind") == "qualification" and request.get("cpu_task_kind") == "solver",
            f"{candidate}: native request kind")
    require(request.get("case_id") == CASE, f"{candidate}: native case")
    require(request.get("expected_frames") == 51 and request.get("expected_dimension") == 3,
            f"{candidate}: native shape")
    counts = request.get("actual_counts")
    require(isinstance(counts, dict), f"{candidate}: native producer counts missing")
    require(counts == {
        "dimension": 3, "fixed": 158559, "floating": 0, "fluid": 31658,
        "moving": 4210, "total": 194427,
    }, f"{candidate}: unexpected Root455 actual counts")
    attempt = request["attempt_id"]
    receipt_path = DATA_CASE / attempt / "execution-receipt.json"
    receipt = load_json(receipt_path)
    require(receipt.get("schema") == "ds02.execution-receipt.v1", f"{candidate}: native receipt schema")
    require(receipt.get("status") == "completed" and int(receipt.get("returncode", -1)) == 0,
            f"{candidate}: native receipt is not completed/0")
    nested = receipt.get("request")
    require(isinstance(nested, dict), f"{candidate}: native nested request missing")
    require(nested.get("attempt_id") == attempt and nested.get("case_id") == CASE,
            f"{candidate}: native receipt identity")
    require(nested.get("actual_counts") == counts, f"{candidate}: native receipt counts")
    output_root = Path(str(receipt["output_root"]))
    require(output_root == DATA_CASE / attempt, f"{candidate}: native output root")
    gencase_receipt_path = Path(request["gencase_receipt"])
    prepared_path = Path(request["prepared_input_report"])
    generated_xml_path = Path(request["generated_xml"])
    gencase_receipt = load_json(gencase_receipt_path)
    require(gencase_receipt.get("status") == "completed"
            and int(gencase_receipt.get("returncode", -1)) == 0,
            f"{candidate}: GenCase receipt is not completed/0")
    prepared = load_json(prepared_path)
    generated = prepared.get("generated_xml_particle_counts")
    require(isinstance(generated, dict), f"{candidate}: prepared count object missing")
    require(
        {key: int(generated.get(key, -1)) for key in ("fixed", "moving", "floating", "fluid")}
        == {key: counts[key] for key in ("fixed", "moving", "floating", "fluid")},
        f"{candidate}: prepared count mismatch",
    )
    require(int(prepared.get("actual_total_particles", -1)) == counts["total"],
            f"{candidate}: prepared total mismatch")
    xml_info = xml_metadata(generated_xml_path)
    qa_report_path = Path(request["actual_initial_qa_report"])
    qa_receipt_path = Path(request["actual_initial_qa_receipt"])
    qa_report = load_json(qa_report_path)
    qa_receipt = load_json(qa_receipt_path)
    require(qa_receipt.get("status") == "completed"
            and int(qa_receipt.get("returncode", -1)) == 0,
            f"{candidate}: initial placement QA receipt is not completed/0")
    return {
        "candidate": candidate,
        "candidate_id": request["candidate_id"],
        "condition_id": spec["condition_id"],
        "native_attempt_id": attempt,
        "native_request_path": str(request_path),
        "native_request_sha256": sha(request_path),
        "native_receipt_path": str(receipt_path),
        "native_receipt_sha256": sha(receipt_path),
        "native_output_root": str(output_root),
        "native_solver_output_root": str(output_root / "solver_output"),
        "native_data_root": str(output_root / "solver_output" / "data"),
        "native_frame0_bi4": str(output_root / "solver_output" / "data" / "Part_0000.bi4"),
        "expected_frames": 51,
        "actual_particle_counts": counts,
        "gencase_attempt_id": request["gencase_attempt_id"],
        "gencase_receipt_path": str(gencase_receipt_path),
        "gencase_receipt_sha256": sha(gencase_receipt_path),
        "prepared_input_report_path": str(prepared_path),
        "prepared_input_report_sha256": sha(prepared_path),
        "generated_xml_path": str(generated_xml_path),
        "generated_xml_sha256": sha(generated_xml_path),
        "generated_bi4_path": request["generated_bi4"],
        "generated_bi4_sha256_producer_declared": request["generated_bi4_sha256"],
        "generated_xml_metadata": xml_info,
        "actual_initial_qa_report_path": str(qa_report_path),
        "actual_initial_qa_report_sha256": sha(qa_report_path),
        "actual_initial_qa_receipt_path": str(qa_receipt_path),
        "actual_initial_qa_receipt_sha256": sha(qa_receipt_path),
        "actual_initial_qa_summary": {
            "basic_placement_mk50_pass": qa_report.get("all_basic_placement_checks_pass",
                                                        qa_report.get("basic_placement_mk50_pass")),
            "numerical_precision_result_accepted": qa_report.get("numerical_precision_result_accepted", False),
        },
        "physical_condition_sha256": request["canonical_physical_binding_sha256"],
        "source_plan_physical_condition_sha256": request["source_plan_physical_condition_sha256"],
        "root455_producer_counts_are_metadata_only": True,
    }


def make_binding(candidate: str, spec: dict[str, Any], native: dict[str, Any]) -> Path:
    physical_dst = PKG / "bindings" / f"{candidate}-physical-binding.json"
    definition_dst = PKG / "inputs" / f"{candidate}-Definition.xml"
    owner_dst = PKG / "inputs" / f"{candidate}-owner.json"
    physical_sha = copy_source(spec["physical_source"], physical_dst)
    definition_sha = copy_source(spec["definition_source"], definition_dst)
    owner_sha = copy_source(spec["owner_source"], owner_dst)
    physical = load_json(physical_dst)
    velocities = physical.get("initial_state", {}).get("velocities_m_per_s", {}).get("fluid")
    require(velocities == [0.0, 0.0, 0.0], f"{candidate}: source fluid initial velocity declaration is not zero")
    binding_path = PKG / "bindings" / f"{candidate}-native-frame0-binding.json"
    files: dict[str, Any] = {
        "native_request": {"path": native["native_request_path"], "sha256": native["native_request_sha256"]},
        "native_receipt": {"path": native["native_receipt_path"], "sha256": native["native_receipt_sha256"]},
        "gencase_receipt": {"path": native["gencase_receipt_path"], "sha256": native["gencase_receipt_sha256"]},
        "prepared_input_report": {"path": native["prepared_input_report_path"], "sha256": native["prepared_input_report_sha256"]},
        "generated_xml": {"path": native["generated_xml_path"], "sha256": native["generated_xml_sha256"]},
        "generated_bi4": {
            "path": native["generated_bi4_path"],
            "sha256": native["generated_bi4_sha256_producer_declared"],
            "hash_semantics": "Root/GenCase producer-declared; source builder did not open or hash BI4",
        },
        "actual_initial_qa_report": {
            "path": native["actual_initial_qa_report_path"],
            "sha256": native["actual_initial_qa_report_sha256"],
        },
        "actual_initial_qa_receipt": {
            "path": native["actual_initial_qa_receipt_path"],
            "sha256": native["actual_initial_qa_receipt_sha256"],
        },
        "physical_binding": {"path": str(physical_dst), "sha256": physical_sha},
        "source_definition": {"path": str(definition_dst), "sha256": definition_sha},
        "source_owner": {"path": str(owner_dst), "sha256": owner_sha},
        "native_output_root": {"path": native["native_output_root"], "sha256": None},
        "native_data_root": {"path": native["native_data_root"], "sha256": None},
        "native_frame0_bi4": {"path": native["native_frame0_bi4"], "sha256": None},
    }
    binding = {
        "schema": "ds02.f5.c082s1.native-frame0-zero-velocity-identity-binding.fresh106.v1",
        "source_only": True,
        "execution_allowed": False,
        "candidate": candidate,
        "candidate_id": native["candidate_id"],
        "case_id": CASE,
        "condition_id": native["condition_id"],
        "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": native["physical_condition_sha256"],
        "source_plan_physical_condition_sha256": native["source_plan_physical_condition_sha256"],
        "native_attempt_id": native["native_attempt_id"],
        "gencase_attempt_id": native["gencase_attempt_id"],
        "expected_frames": native["expected_frames"],
        "actual_particle_counts": native["actual_particle_counts"],
        "dimension": 3,
        "fluid_type_code": 3,
        "native_bed_mk": 50,
        "source_mkbound": 40,
        "files": files,
        "partvtk": str(PARTVTK),
        "partvtk_sha256_producer_declared": PARTVTK_SHA,
        "source_defined_initial_velocity": {
            "vector_m_per_s": velocities,
            "tolerance_m_per_s": 1.0e-8,
            "proof": "F5 C082S1 physical binding initial_state.fluid.velocities_m_per_s; native frame-0 value must be measured from Part_0000.bi4 by this worker",
            "gencase_csv_velocity_not_substituted": True,
        },
        "native_identity_contract": {
            "uid_field": "Idp",
            "zone_field": "Zone",
            "type_field": "Type",
            "mk_field": "Mk",
            "type_codes": {"0": "fixed", "1": "moving", "2": "floating", "3": "fluid"},
            "fluid_mk_is_observed_by_worker": True,
            "native_bed_marker_mk": 50,
            "source_mkbound_maps_to_native_mk": {"source_mkbound": 40, "native_mk": 50},
        },
        "historical_exact_dp_lattice": {
            "threshold": 1.0e-6,
            "diagnostic_only": True,
            "accepted_as_stage1_gate": False,
            "status": "Root314 exact-DP numerical negative retained; fresh106 does not loosen or relabel it",
        },
        "worker_sha256": sha(WORKER),
        "full801_authorized": False,
        "q_n_granted": False,
        "visual_acceptance": False,
        "production_approval": "none",
        "independent_case_count_increment": 0,
        "science_payloads_read_or_hashed_by_source_builder": False,
    }
    dump(binding_path, binding)
    return binding_path


def input_closure(candidate: str, native: dict[str, Any], binding_path: Path) -> tuple[list[str], dict[str, str | None]]:
    source_files = [
        binding_path,
        PKG / "inputs" / f"{candidate}-Definition.xml",
        PKG / "inputs" / f"{candidate}-owner.json",
        PKG / "bindings" / f"{candidate}-physical-binding.json",
        WORKER,
        PKG / "scripts" / "validate_fresh106.py",
        ROOT230 / "launch.py",
        ROOT230 / "root_native_home_floor_inventory_policy.py",
        RESOURCES,
        Path(native["native_request_path"]),
        Path(native["native_receipt_path"]),
        Path(native["gencase_receipt_path"]),
        Path(native["prepared_input_report_path"]),
        Path(native["generated_xml_path"]),
        Path(native["actual_initial_qa_report_path"]),
        Path(native["actual_initial_qa_receipt_path"]),
        PYTHON,
        PARTVTK,
    ]
    files: list[str] = []
    hashes: dict[str, str | None] = {}
    for path in source_files:
        text = str(path)
        files.append(text)
        if path == PYTHON:
            hashes[text] = "a2f33f6a006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae"
        elif path == PARTVTK:
            hashes[text] = PARTVTK_SHA
        elif path.suffix.lower() in HASHABLE_SUFFIXES:
            require(path.is_file(), f"closure source missing: {path}")
            hashes[text] = sha(path)
        else:
            raise ValueError(f"unexpected nonmetadata closure path: {path}")
    future = [
        native["native_frame0_bi4"],
        native["native_data_root"],
        native["generated_bi4_path"],
        "<root-bind:partvtk_output_csv>",
        "<root-bind:frame0_qa_report>",
        "<root-bind:frame0_qa_receipt>",
    ]
    for item in future:
        files.append(item)
        hashes[item] = None
    return sorted(set(files)), hashes


def root230_provenance() -> dict[str, Any]:
    return {
        "entrypoint": str(ROOT230 / "launch.py"),
        "entrypoint_sha256": ROOT230_LAUNCH_SHA,
        "policy_source": str(ROOT230 / "root_native_home_floor_inventory_policy.py"),
        "policy_source_sha256": ROOT230_POLICY_SHA,
        "source_declared_policy_sha256": ROOT142_POLICY_SHA,
        "profile": "root_home_floor_no_legacy_dataset_walk_native_v1",
        "launch_owner": "root",
        "gpu_protection_required": True,
        "solver_kinds_only": ["qualification", "production"],
    }


def make_request(candidate: str, spec: dict[str, Any], native: dict[str, Any],
                 binding_path: Path) -> Path:
    files, hashes = input_closure(candidate, native, binding_path)
    binding_sha = sha(binding_path)
    request_path = PKG / "requests" / f"{candidate}-native-frame0-zero-velocity-qa-request.json"
    binding = load_json(binding_path)
    request = {
        "schema": "ds02.runner-request.v2",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "attempt_id": spec["qa_attempt"],
        "candidate_id": native["candidate_id"],
        "case_id": CASE,
        "family_id": "F5",
        "condition_id": native["condition_id"],
        "physical_case_id": binding["physical_case_id"],
        "physical_binding_path": str(binding_path),
        "physical_binding_sha256": binding_sha,
        "physical_condition_sha256": native["physical_condition_sha256"],
        "source_plan_physical_condition_sha256": native["source_plan_physical_condition_sha256"],
        "binding": str(binding_path),
        "binding_sha256": binding_sha,
        "worker": str(WORKER),
        "worker_sha256": sha(WORKER),
        "depends_on_attempt": native["native_attempt_id"],
        "depends_on_attempts": [native["native_attempt_id"]],
        "native_attempt_id": native["native_attempt_id"],
        "native_receipt": native["native_receipt_path"],
        "native_receipt_sha256": native["native_receipt_sha256"],
        "gencase_attempt_id": native["gencase_attempt_id"],
        "actual_counts": native["actual_particle_counts"],
        "expected_frames": 51,
        "expected_frame_index": 0,
        "expected_dimension": 3,
        "expected_particle_axis": 194427,
        "expected_particles": 194427,
        "expected_fixed_particles": 158559,
        "expected_moving_particles": 4210,
        "expected_floating_particles": 0,
        "expected_fluid_particles": 31658,
        "fluid_type_code": 3,
        "native_bed_mk": 50,
        "source_mkbound": 40,
        "source_defined_initial_velocity_m_per_s": [0.0, 0.0, 0.0],
        "source_defined_initial_velocity_tolerance_m_per_s": 1.0e-8,
        "native_velocity_must_be_measured_from_part_0000_bi4": True,
        "gencase_csv_velocity_must_not_be_used_as_native_proof": True,
        "command": [
            str(PYTHON), str(WORKER), "--binding", str(binding_path),
            "--output-dir", "{attempt_root}/native-frame0-audit",
        ],
        "cwd": str(LAB),
        "launch_owner": "root",
        "kind_semantics": "registered CPU metadata/PartVTK audit only",
        "disabled": True,
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "solver_allowed": False,
        "conversion_allowed": False,
        "source_only": True,
        "shared_registry_write_allowed": False,
        "arrays_allowed": False,
        "array_edit_allowed": False,
        "cpu_threads": 2,
        "estimated_peak_gpu_mib": 0,
        "estimated_storage_bytes": 2147483648,
        "max_wall_seconds": 1800,
        "root_inventory_policy_source_sha256": ROOT230_POLICY_SHA,
        "root_corrected_source_inventory_policy_sha256": {
            "actual_native230": ROOT230_POLICY_SHA,
            "source_declared": ROOT142_POLICY_SHA,
        },
        "root230_dispatch_provenance": root230_provenance(),
        "resource_window_approval": str(RESOURCES),
        "resource_window_approval_sha256": sha(RESOURCES),
        "input_files": files,
        "input_sha256": hashes,
        "input_sha256_provenance": "source/JSON/XML metadata only; BI4/CSV/H5/VTK/DAT remain Root-bound and unhashable here",
        "future_output_hashes": {
            "frame0_qa_report_sha256": None,
            "frame0_qa_receipt_sha256": None,
            "partvtk_csv_sha256": None,
        },
        "future_product_paths": {
            "frame0_qa_report": None,
            "frame0_qa_receipt": None,
            "partvtk_csv": None,
        },
        "historical_exact_dp_lattice": binding["historical_exact_dp_lattice"],
        "native_saved_state_gate": {
            "root455_receipt_completed_zero": True,
            "all_51_states_must_remain_root_owned": True,
            "first_state_part_0000_bi4_required": True,
            "zero_velocity_must_be_measured_after_partvtk": True,
            "typed_enablement_after_this_qa": "Root review only; no automatic enablement",
        },
        "full801_authorized": False,
        "full16_authorized": False,
        "q_n_granted": False,
        "visual_acceptance": False,
        "production_approval": "none",
        "independent_case_count_increment": 0,
        "old_attempt_modification_forbidden": True,
        "science_payloads_read_or_hashed_by_source_builder": False,
    }
    dump(request_path, request)
    return request_path


def write_attestation(candidate: str, native: dict[str, Any], request_path: Path) -> None:
    dump(PKG / "metadata" / f"{candidate}-root455-frame0-attestation.json", {
        "schema": "ds02.f5.c082s1.root455-native-frame0-attestation.fresh106.v1",
        "candidate": candidate,
        "case_id": CASE,
        "native_attempt_id": native["native_attempt_id"],
        "native_receipt": native["native_receipt_path"],
        "native_receipt_sha256": native["native_receipt_sha256"],
        "native_status": "completed/0 from actual Root455 JSON receipt",
        "native_output_root": native["native_output_root"],
        "expected_saved_frames": 51,
        "actual_particle_counts": native["actual_particle_counts"],
        "gencase_attempt_id": native["gencase_attempt_id"],
        "gencase_receipt": native["gencase_receipt_path"],
        "gencase_receipt_sha256": native["gencase_receipt_sha256"],
        "generated_xml": native["generated_xml_path"],
        "generated_xml_sha256": native["generated_xml_sha256"],
        "generated_bi4": native["generated_bi4_path"],
        "generated_bi4_sha256_producer_declared": native["generated_bi4_sha256_producer_declared"],
        "actual_initial_qa_report": native["actual_initial_qa_report_path"],
        "actual_initial_qa_report_sha256": native["actual_initial_qa_report_sha256"],
        "frame0_native_qa": "pending registered PartVTK worker",
        "typed_enablement": "blocked until Root reviews the completed frame0 QA",
        "science_payloads_read_or_hashed_by_source_builder": False,
        "request_path": str(request_path),
        "request_sha256": sha(request_path),
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
    })


def write_readme() -> None:
    text = f"""# F5 fresh106: native frame-0 identity and zero-velocity QA

This is a source-only handoff for the two already completed Root455 short
native attempts:

* root-stage1-f5-c082s1-A080-short-native-qualification-104-root455
* root-stage1-f5-c082s1-A120-short-native-qualification-104-root455

The producer metadata is bound to the actual Gen426 prepared reports and the
actual Root455 receipts. Both candidates have the producer counts
194427 = 158559 fixed + 4210 moving + 0 floating + 31658 fluid, 3-D, and
51 requested saved states.

The two requests in requests/ are deliberately disabled
(kind=cpu, cpu_task_kind=audit, launch=false, execution_allowed=false).
A Root-registered CPU worker may be enabled only after review. It invokes the
official PartVTK executable on the actual solver-saved
solver_output/data/Part_0000.bi4, then independently checks:

* the frame-0 summary (t=0, Np=194427, Nfluid=31658);
* finite positions, mass and density;
* integral Zone/Idp/Type/Mk fields, zero Zone, consecutive unique Idp values,
  exact producer Type counts, and unique coordinates with non-overlap between
  Type partitions;
* genuine 3-D extent;
* the native Type-3 fluid count and its measured initial velocity against the
  source declaration [0, 0, 0] with tolerance 1e-8 m/s.

The worker never substitutes GenCase CSV velocity for the native saved state.
The source builder did not open or hash BI4, H5, CSV, VTK or motion DAT. Those
payloads remain Root-owned runtime inputs; the future worker report, receipt
and PartVTK CSV digests are null here.

The source marker mapping remains mkbound=40 to native bed Mk=50.
The historical exact-DP lattice threshold 1e-6 failure is retained as a
separate numerical negative and is neither loosened nor relabelled by this
identity QA. This package grants no Q-N, visual acceptance, full801/full16
approval or independent case count. Root must review the completed frame-0
report before enabling fresh105 typed conversion.

Validate metadata and disabled-request closure with:

    python3 scripts/validate_fresh106.py

No solver, PartVTK, converter, renderer, array reader, registry write or
ledger mutation was started during source preparation.
"""
    (PKG / "README.md").write_text(text, encoding="utf-8")


def write_manifest() -> None:
    files: dict[str, str] = {}
    for path in sorted(PKG.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        require(path.suffix.lower() in HASHABLE_SUFFIXES,
                f"fresh106 package contains a non-metadata payload: {path}")
        files[str(path.relative_to(PKG))] = sha(path)
    dump(PKG / "manifest.json", {
        "schema": "ds02.f5.c082s1.native-frame0-zero-velocity-identity-package-manifest.fresh106.v1",
        "source_only": True,
        "science_payloads_in_package": False,
        "science_payloads_read_or_hashed_by_source_builder": False,
        "files": files,
        "future_output_hashes": {
            "frame0_qa_report_sha256": None,
            "frame0_qa_receipt_sha256": None,
            "partvtk_csv_sha256": None,
        },
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
    })


def main() -> int:
    PKG.mkdir(parents=True, exist_ok=True)
    native: dict[str, dict[str, Any]] = {}
    bindings: dict[str, Path] = {}
    requests: dict[str, Path] = {}
    for candidate, spec in CANDIDATES.items():
        native[candidate] = check_native(candidate, spec)
        bindings[candidate] = make_binding(candidate, spec, native[candidate])
        requests[candidate] = make_request(candidate, spec, native[candidate], bindings[candidate])
        write_attestation(candidate, native[candidate], requests[candidate])
    dump(PKG / "metadata" / "fresh106-source-plan.json", {
        "schema": "ds02.f5.c082s1.fresh106-source-plan.v1",
        "candidates": {
            candidate: {
                "native_attempt_id": value["native_attempt_id"],
                "actual_counts": value["actual_particle_counts"],
                "expected_frames": value["expected_frames"],
                "frame0_qa_request": str(requests[candidate]),
                "frame0_qa_binding": str(bindings[candidate]),
                "future_frame0_report_sha256": None,
                "future_frame0_receipt_sha256": None,
            }
            for candidate, value in native.items()
        },
        "source_defined_initial_fluid_velocity_m_per_s": [0.0, 0.0, 0.0],
        "historical_exact_dp_lattice": {
            "threshold": 1.0e-6,
            "diagnostic_only": True,
            "accepted_as_stage1_gate": False,
            "status": "negative retained",
        },
        "typed_enablement": "blocked until native frame0 QA is actual completed/0 and Root reviewed",
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "science_payloads_read_or_hashed_by_source_builder": False,
    })
    write_readme()
    write_manifest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
