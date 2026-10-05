#!/usr/bin/env python3
"""Build six lattice-aligned F4 drop-gap source cases.

Only the falling-drop point z literal is changed in the frozen mother
Definition.  The builder writes source XML and small JSON contracts; it does
not invoke GenCase, a decoder, a solver, a converter, or a renderer.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any

OLD_LITERAL = "0.42500000000000004"
GENCASE = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
SOLVER = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
PYTHON = "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
AUDIT = "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_f4_centered_reference_v1.py"
STRICT_GUARD = "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
DATA_ROOT = "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4"
SCHEMA = "ds02.f4.lattice-aligned-fallback6.source-package.v1"
PLANNED_COUNTS = {"fixed": 24161, "fluid": 59072, "total": 83233}


def cjson(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def csha(value: Any) -> str:
    return hashlib.sha256(cjson(value).encode("utf-8")).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def source_payload(endpoint: dict[str, Any]) -> dict[str, Any]:
    gap = float(endpoint["gap_m"])
    z = str(endpoint["drop_point_z_literal"])
    # Keep a deterministic long decimal literal for the derived source
    # region.  It describes the intended lattice phase; it is not a native
    # particle count or a generated-array observation.
    low_z = f"{gap + 0.2:.2f}" + "000000000000004"
    return {
        "axis": "initial_drop_height_gap_m",
        "canonical_physical_case_id": endpoint["physical_case_id"],
        "case_id": endpoint["endpoint_id"],
        "dp_m": "0.01",
        "drop_low_xyz_literals": ["0.47499999999999998", "0.125", low_z],
        "drop_point_z_literal": z,
        "drop_size_xyz_literals": ["0.25000000100000003", "0.15000000099999999", "0.130000001"],
        "drop_velocity_xyz_literals": ["0", "0", "-0.5"],
        "gap_m": f"{gap:.5f}",
        "lattice_alignment": {
            "drop_point_z_formula": "gap_m + 0.205 m",
            "drop_region_low_z_formula": "gap_m + 0.200 m",
            "phase": "dp/2-centered source lattice; only drop z varies",
        },
        "mother": "F4_DROP_CENTERED_REFERENCE_001_DP010",
        "pool_low_xyz_literals": ["0.085000000000000006", "0.044999999999999998", "0.044999999999999998"],
        "pool_size_xyz_literals": ["1.0300000010000001", "0.31000000100000003", "0.15000000099999999"],
        "x_offset_m": "0.0",
        "y_offset_m": "0.0",
    }


def physical_binding(endpoint: dict[str, Any]) -> dict[str, Any]:
    gap = float(endpoint["gap_m"])
    case_id = endpoint["physical_case_id"]
    low_z = round(gap + 0.2, 12)
    drop = {"label": "falling_drop", "low_m": [0.47, 0.12, low_z], "mkfluid": 1, "size_m": [0.26, 0.16, 0.14]}
    pool = {"label": "pool", "low_m": [0.08, 0.04, 0.04], "mkfluid": 0, "size_m": [1.04, 0.32, 0.16]}
    source_regions = {"drop": copy.deepcopy(drop), "pool": copy.deepcopy(pool)}
    continuum = {"drop": 5.824000000000001, "pool": 53.24800000000001}
    return {
        "schema": "ds-data-02.physical-binding.v1",
        "family_id": "F4",
        "control_family_id": "F4_native_dbc_verlet_wendland_v1",
        "geometry_family_id": "F4_finite_drop_pool_finite_geometry_v1",
        "lineage_group_id": "finite_drop_pool_frozen_geometry_control_domain",
        "mechanism_id": "finite_drop_pool",
        "paired_background_id": "finite_drop_pool",
        "physical_case_id": case_id,
        "gravity_m_s2": [0.0, 0.0, -9.81],
        "density_kg_m3": 1000.0,
        "open_inlet": False,
        "periodic_boundary": False,
        "mass_policy": "native_rho_dp_cubed_no_rescaling; actual native mass pending GenCase/QA",
        "controls": {"boundary": "DBC", "density_dt": 2, "density_dt_value": 0.1, "kernel": "Wendland", "step_algorithm": "Verlet", "viscosity": 0.08},
        "geometry": {
            "drop": drop,
            "pool": pool,
            "tank": {"low_m": [0.0, 0.0, 0.0], "size_m": [1.2, 0.4, 0.6]},
            "wall_box": {"low_m": [0.0, 0.0, 0.0], "size_m": [1.2, 0.4, 0.6]},
        },
        "initial_state": {
            "source_labels": {"mkfluid:0": "pool", "mkfluid:1": "falling_drop"},
            "source_regions": source_regions,
            "velocities_m_per_s": {"mkfluid:0": [0.0, 0.0, 0.0], "mkfluid:1": [0.0, 0.0, -0.5]},
            "continuum_mass_by_source_kg": continuum,
            "initial_mass_by_source_kg": None,
            "initial_mass_total_kg": None,
            "initial_native_mass_status": "pending actual generated native weights; no rescale",
            "mass_policy": "native_rho_dp_cubed_no_rescaling",
        },
        "event_window": {
            "time_start_s": 0.0,
            "time_end_s": 1.2,
            "expected_first_contact_range_s": [0.17, 0.35],
            "right_censor_policy": "qualification_requires_completed_tail_or_explicit_censoring",
            "sequence": ["separated_initial_state", "first_pool_contact", "maximum_spread", "rebound_or_recontact", "transport_tail"],
        },
        "parameters": {"gap_m": gap, "speed_m_per_s": 0.5, "x_offset_m": 0.0, "y_offset_m": 0.0},
    }


def future_paths(endpoint_id: str) -> dict[str, str]:
    gen_attempt = "root-stage1-f4-fallback6-genuine-gencase-087"
    qa_attempt = "root-stage1-f4-fallback6-native-initial-qa-087"
    native_attempt = f"root-stage1-f4-{endpoint_id.lower().replace('_', '-')}-full1201-native-qualification-087"
    base = f"{DATA_ROOT}/F4_FALLBACK6_LATTICE_DP010"
    gen = f"{base}/{gen_attempt}/gencase/{endpoint_id}"
    qa = f"{DATA_ROOT}/{endpoint_id}/{qa_attempt}"
    native = f"{DATA_ROOT}/{endpoint_id}/{native_attempt}"
    return {
        "gencase_result": f"{base}/{gen_attempt}/gencase-preflight-result.json",
        "gencase_receipt": f"{gen}/gencase-receipt.json",
        "generated_xml": f"{gen}/{endpoint_id}.xml",
        "generated_bi4": f"{gen}/{endpoint_id}.bi4",
        "initial_qa_index": f"{qa}/initial-native-qa-index.json",
        "initial_qa_binding": f"{qa}/initial-native-qa-binding.json",
        "initial_qa_receipt": f"{qa}/execution-receipt.json",
        "native_receipt": f"{native}/execution-receipt.json",
    }


def make_owner(endpoint: dict[str, Any], source_path: Path, source_hash: str, plan_path: Path) -> dict[str, Any]:
    binding = physical_binding(endpoint)
    binding_hash = csha(binding)
    payload = source_payload(endpoint)
    futures = future_paths(endpoint["endpoint_id"])
    return {
        "schema": "ds02.f4.lattice-aligned-fallback6.canonical-owner.v1",
        "family_id": "F4",
        "case_id": endpoint["endpoint_id"],
        "topphysical_case_id": endpoint["physical_case_id"],
        "claim_boundary": "Source-only lattice-aligned candidate. Root must run genuine GenCase and native initial QA; no native mass, QA, visual, precision, Q-N, production, or independent-case credit is claimed.",
        "source_only": True,
        "launch_allowed": False,
        "independent_case_count_increment": 0,
        "production_approval": "none",
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "visual_status": "pending Root genuine GenCase plus native initial QA",
        "physical_binding": binding,
        "physical_binding_sha256": binding_hash,
        "physical_condition_sha256": binding_hash,
        "source_plan_condition_payload": payload,
        "source_plan_condition_sha256": csha(payload),
        "source_lattice_alignment": {
            "dp_m": 0.01,
            "drop_point_z_literal": endpoint["drop_point_z_literal"],
            "drop_region_low_z_m": binding["geometry"]["drop"]["low_m"][2],
            "phase": "aligned to the frozen half-dp source lattice; drop z is the sole mutation",
            "validation_status": "source XML/byte contract only; native population checks pending actual GenCase QA",
        },
        "source_recipe": {
            "dp_m": 0.01,
            "time_max_s": 1.2,
            "time_out_s": 0.001,
            "native_frame_count": 1201,
            "fixed_native_types": [0],
            "fluid_native_types": [3],
            "moving_native_types": [],
            "mass_policy": "native body support weights; rho*dp^3 physical mass; no continuum rescale",
            "source_particle_counts": None,
            "planned_lattice_counts": PLANNED_COUNTS,
            "planned_lattice_counts_status": "reference-only expectation; must be replaced by actual generated XML counts",
        },
        "source_definition": {
            "path": str(source_path),
            "sha256": source_hash,
            "mother_path": str(Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261002/centered_reference_matrix_001/F4_DROP_CENTERED_REFERENCE_001_DP010_Def.xml")),
            "mother_sha256": endpoint["mother_definition_sha256"],
            "changed_literal": endpoint["drop_point_z_literal"],
        },
        "future_attempts": {
            "gencase": "root-stage1-f4-fallback6-genuine-gencase-087",
            "initial_qa": "root-stage1-f4-fallback6-native-initial-qa-087",
            "native": futures["native_receipt"].split("/")[-2],
        },
        "future_inputs": futures,
        "future_outputs": {
            "gencase_receipt_sha256": None,
            "generated_xml_sha256": None,
            "generated_bi4_producer_sha256": None,
            "initial_qa_index_sha256": None,
            "initial_qa_binding_sha256": None,
            "initial_qa_receipt_sha256": None,
            "native_receipt_sha256": None,
        },
    }


def make_metadata(endpoint: dict[str, Any], owner: dict[str, Any], source_path: Path, source_hash: str) -> dict[str, Any]:
    physical = owner["physical_binding"]
    return {
        "schema": "ds02.f4.lattice-aligned-fallback6.metadata.v1",
        "family_id": "F4",
        "case_id": endpoint["endpoint_id"],
        "physical_case_id": physical["physical_case_id"],
        "physical_condition_sha256": owner["physical_condition_sha256"],
        "physical_binding": copy.deepcopy(physical),
        "physical_binding_sha256": owner["physical_binding_sha256"],
        "dp_m": 0.01,
        "source_regions": copy.deepcopy(physical["initial_state"]["source_regions"]),
        "expected_counts_by_source": None,
        "planned_lattice_counts_by_source": {"drop": 5824, "pool": 53248},
        "actual_native_counts_by_source": None,
        "continuous_mass_by_source_kg": copy.deepcopy(physical["initial_state"]["continuum_mass_by_source_kg"]),
        "native_mass_by_source_kg": None,
        "mass_status": "continuum geometry derivation only; actual native weights pending Root GenCase/QA",
        "definition_sha256": source_hash,
        "original_definition": str(source_path),
        "original_source_sha256": {str(source_path): source_hash},
        "generated_xml_partition": None,
        "raw_native_marker_arrays": {"Mk": "pending Root native QA", "Type": "pending Root native QA"},
        "arrays_read_by_source": False,
        "source_only": True,
        "status": "source_only_disabled",
        "claim_boundary": "Small source/XML contract only; no generated XML/BI4 or actual particle count is present.",
    }


def common_request_fields(*, scope: str, kind: str, attempt: str, inputs: list[Path], package: Path) -> dict[str, Any]:
    request_kind = "cpu" if kind in {"gencase", "audit"} else kind
    worktree_root = package.parents[5].resolve()
    return {
        "schema": "ds02.runner-request.v2",
        "scope_id": scope,
        "family_id": "F4",
        "attempt_id": attempt,
        "kind": request_kind,
        "cpu_task_kind": kind,
        "cpu_threads": 2,
        "cwd": str(worktree_root),
        "worktree_root": str(worktree_root),
        "launch": False,
        "launch_allowed": False,
        "launch_owner": "root",
        "status": "source_only_disabled",
        "source_only": True,
        "independent_case_count_increment": 0,
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "production_approval": "none",
        "input_files": [str(path) for path in inputs],
        "input_sha256": {str(path): sha256(path) for path in inputs},
        "deferred_input_sha256": {},
        "root_review_required": True,
    }


def build(plan_path: Path) -> None:
    plan_path = plan_path.resolve()
    plan = load(plan_path)
    package = plan_path.parent.resolve()
    mother = Path(plan["mother_binding"]["source_definition_xml"])
    mother_bytes = mother.read_bytes()
    if sha256(mother) != plan["mother_binding"]["source_definition_xml_sha256"]:
        raise RuntimeError("mother hash mismatch")
    old = OLD_LITERAL.encode("ascii")
    if mother_bytes.count(old) != 1:
        raise RuntimeError("expected one mother drop point token")
    receipt_rows: list[dict[str, Any]] = []
    for endpoint in plan["endpoints"]:
        eid = endpoint["endpoint_id"]
        new = endpoint["drop_point_z_literal"].encode("ascii")
        if len(new) != len(old):
            raise RuntimeError(f"literal length drift: {eid}")
        output = package / endpoint["source_definition_output"]
        output_bytes = mother_bytes.replace(old, new, 1)
        if output_bytes == mother_bytes or output_bytes.count(new) != 1:
            raise RuntimeError(f"invalid replacement: {eid}")
        ET.fromstring(output_bytes)
        output.write_bytes(output_bytes)
        source_hash = sha256(output)
        endpoint["source_definition_sha256"] = source_hash
        endpoint["mother_definition_sha256"] = sha256(mother)
        binding = physical_binding(endpoint)
        endpoint["physical_condition_sha256"] = csha(binding)
        endpoint["source_plan_condition_sha256"] = csha(source_payload(endpoint))
        owner = make_owner(endpoint, output, source_hash, plan_path)
        metadata = make_metadata(endpoint, owner, output, source_hash)
        dump(package / "owners" / f"{eid}.owner.json", owner)
        dump(package / "metadata" / f"{eid}.metadata.json", metadata)
        receipt_rows.append({
            "endpoint_id": eid,
            "source_definition": str(output),
            "source_definition_sha256": source_hash,
            "source_definition_bytes": len(output_bytes),
            "mother_definition_sha256": sha256(mother),
            "old_literal": OLD_LITERAL,
            "new_literal": endpoint["drop_point_z_literal"],
            "changed_byte_count": sum(a != b for a, b in zip(old, new)),
            "binary_or_particle_outputs": [],
        })
    dump(plan_path, plan)
    receipt = {
        "schema": "ds02.f4.lattice-aligned-fallback6.source-build-receipt.v1",
        "family_id": "F4",
        "scope_id": plan["scope_id"],
        "source_plan": str(plan_path),
        "source_plan_sha256": sha256(plan_path),
        "mother_definition": str(mother),
        "mother_definition_sha256": sha256(mother),
        "endpoint_count": len(receipt_rows),
        "endpoints": receipt_rows,
        "mutation_policy": "one drop point z literal per endpoint; every other source byte is preserved",
        "lattice_policy": "gaps .190/.200/.210/.230/.240/.250 use point_z=gap+.205 and region_low_z=gap+.200 at dp=.01",
        "tools_invoked": [],
        "gencase_invoked": False,
        "native_qa_invoked": False,
        "solver_invoked": False,
        "binary_or_particle_outputs": [],
        "launch_allowed": False,
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
    }
    dump(package / "source-build-receipt.json", receipt)

    worker_gen = package / "workers" / "run_f4_gencase_preflight_v3.py"
    worker_qa = package / "workers" / "run_f4_fallback_native_initial_qa_v1.py"
    builder = package / "builders" / "build_f4_lattice_fallback_v1.py"
    for endpoint in plan["endpoints"]:
        eid = endpoint["endpoint_id"]
        owner_path = package / "owners" / f"{eid}.owner.json"
        metadata_path = package / "metadata" / f"{eid}.metadata.json"
        source_path = package / endpoint["source_definition_output"]
        inputs = [plan_path, package / "source-build-receipt.json", owner_path, metadata_path, source_path, builder, Path(STRICT_GUARD)]
        attempt = f"root-stage1-f4-{eid.lower().replace('_', '-')}-genuine-gencase-087"
        gencase = common_request_fields(scope=plan["scope_id"], kind="gencase", attempt=attempt, inputs=inputs, package=package)
        gencase.update({
            "case_id": eid,
            "command": [GENCASE, str(source_path.with_suffix("")), "{attempt_root}/" + eid + "/" + eid, "-save:all", "-threads:2"],
            "max_wall_seconds": 1800,
            "estimated_storage_bytes": 67108864,
            "expected_outputs": {"gencase_receipt": None, "generated_xml": None, "generated_bi4": None, "all_future_sha256": None},
            "deferred_input_files": [],
            "disabled_reason": "Root must enable this distinct source Definition only after reviewing the lattice-aligned mutation and resource window; no generated output exists in this package.",
        })
        dump(package / "requests" / f"{eid}-gencase.request.json", gencase)

        qa_attempt = f"root-stage1-f4-{eid.lower().replace('_', '-')}-native-initial-qa-087"
        qa_inputs = [plan_path, package / "source-build-receipt.json", owner_path, metadata_path, worker_qa, package / "README.md", Path(STRICT_GUARD)]
        qa = common_request_fields(scope=plan["scope_id"], kind="audit", attempt=qa_attempt, inputs=qa_inputs, package=package)
        future = future_paths(eid)
        qa.update({
            "case_id": eid,
            "command": [PYTHON, str(worker_qa), "--plan", str(plan_path), "--gencase-binding", "{gencase_binding}", "--owner-root", str(package / "owners"), "--audit-script", AUDIT, "--output-root", "{attempt_root}", "--python", PYTHON],
            "max_wall_seconds": 1800,
            "estimated_storage_bytes": 1073741824,
            "deferred_input_files": [future["gencase_receipt"], future["generated_xml"], future["generated_bi4"], "{gencase_binding}"],
            "deferred_input_sha256": {future["gencase_receipt"]: None, future["generated_xml"]: None, future["generated_bi4"]: None, "{gencase_binding}": None},
            "expected_outputs": {"index": None, "binding": None, "execution_receipt": None, "all_future_sha256": None},
            "arrays_read_by_source": False,
            "bi4_read_by_source": False,
            "disabled_reason": "Enable only after this endpoint's genuine GenCase per-case receipt, generated XML and BI4 are completed0 and bound; the worker then invokes the pinned official native initial QA audit.",
        })
        dump(package / "requests" / f"{eid}-initial-native-qa.request.json", qa)

        native_attempt = f"root-stage1-f4-{eid.lower().replace('_', '-')}-full1201-native-qualification-087"
        native_inputs = [plan_path, package / "source-build-receipt.json", owner_path, metadata_path, source_path, Path(STRICT_GUARD)]
        native = common_request_fields(scope=plan["scope_id"], kind="qualification", attempt=native_attempt, inputs=native_inputs, package=package)
        generated_prefix = future_paths(eid)["generated_bi4"][:-4]
        native.update({
            "case_id": eid,
            "command": [SOLVER, generated_prefix, "{attempt_root}/solver_output", "-tmax:1.2", "-tout:0.001"],
            "cwd": str(Path(generated_prefix).parent),
            "gencase_receipt": future_paths(eid)["gencase_receipt"],
            "gencase_receipt_sha256": None,
            "max_wall_seconds": 14400,
            "estimated_peak_gpu_mib": 8192,
            "estimated_storage_bytes": 214748364800,
            "deferred_input_files": [future_paths(eid)["generated_xml"], future_paths(eid)["generated_bi4"], future_paths(eid)["initial_qa_index"], future_paths(eid)["initial_qa_binding"]],
            "deferred_input_sha256": {future_paths(eid)["generated_xml"]: None, future_paths(eid)["generated_bi4"]: None, future_paths(eid)["initial_qa_index"]: None, future_paths(eid)["initial_qa_binding"]: None},
            "expected_outputs": {"execution_receipt": None, "data_root": None, "all_future_sha256": None},
            "disabled_reason": "Root may enable only after actual GenCase and native initial QA pass for this exact physical binding; solver recipe remains dp=.01, tmax=1.2 s, tout=.001 s, 1201 frames.",
        })
        dump(package / "requests" / f"{eid}-full1201-native-qualification.request.json", native)

    dump(package / "requests" / "index.json", {
        "schema": "ds02.f4.lattice-aligned-fallback6.request-index.v1",
        "scope_id": plan["scope_id"],
        "endpoint_count": len(plan["endpoints"]),
        "gencase_requests": [f"{e['endpoint_id']}-gencase.request.json" for e in plan["endpoints"]],
        "initial_native_qa_requests": [f"{e['endpoint_id']}-initial-native-qa.request.json" for e in plan["endpoints"]],
        "native_requests": [f"{e['endpoint_id']}-full1201-native-qualification.request.json" for e in plan["endpoints"]],
        "launch_allowed": False,
        "future_hash_policy": "all GenCase/native QA/native outputs remain null until Root executes and records actual receipts",
    })
    dump(package / "manifest.json", {
        "schema": SCHEMA,
        "family_id": "F4",
        "scope_id": plan["scope_id"],
        "gaps_m": [float(e["gap_m"]) for e in plan["endpoints"]],
        "canonical_ids": [e["physical_case_id"] for e in plan["endpoints"]],
        "endpoint_count": len(plan["endpoints"]),
        "physical_count_increment": 0,
        "launch_allowed": False,
        "source_only": True,
        "root216_evidence": {"path": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_INTERNAL_GAP8_DP010_INITIAL_QA/root-stage1-f4-internal8-native-initial-qa-nested-adapter-repair-216/initial-native-qa-index.json", "status": "failed_preserved; all_source_population_checks_false"},
        "read_policy": {"bi4_arrays_read": False, "csv_arrays_read": False, "h5_arrays_read": False, "source_agent_jobs_started": False, "source_agent_shared_registry_writes": False},
        "request_index": "requests/index.json",
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args()
    build(args.plan)
    print(json.dumps({"status": "source_only", "scope_id": load(args.plan)["scope_id"], "endpoint_count": 6, "jobs_started": False, "arrays_read": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
