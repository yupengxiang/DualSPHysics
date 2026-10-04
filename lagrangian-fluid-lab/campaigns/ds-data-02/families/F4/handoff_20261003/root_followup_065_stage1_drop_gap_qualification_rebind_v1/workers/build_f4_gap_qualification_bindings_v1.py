#!/usr/bin/env python3
"""Build disabled, runtime-compatible F4 gap qualification bindings.

This worker prepares the inputs for the two full-window F4 endpoint
qualification requests after Root has completed and reviewed the 069 actual
native QA.  It reads the 069 index and its endpoint XML/QA reports, then
derives the actual particle counts from the all-numeric XML.  The genuine
individual GenCase commands and their return codes come from the 063
``gencase-preflight-result.json``.  The 063 shared execution receipt is
required to remain failed because its wrapper did not bind the XML count.

The worker copies exact XML/BI4 bytes into a new preparation scope and writes
per-endpoint evidence receipts containing the fields required by
``runtime.validate_request``.  Those receipts are explicitly derived
runtime evidence: this worker never runs GenCase, never decodes BI4, and
never claims that a new GenCase process ran.  The generated solver requests
remain disabled and owned by Root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


SCHEMA = "ds02.f4.drop-gap-qualification-input-binding-index.v1"
RECEIPT_SCHEMA = "ds02.f4.drop-gap-runtime-gencase-evidence-receipt.v1"
FAILURE_SCHEMA = "ds02.f4.drop-gap-original-063-failure-binding.v2"
SOLVER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
)
SOLVER_OPTIONS = ["-tmax:1.2", "-tout:0.001"]
EXPECTED_ENDPOINTS = (
    "F4_DROP_ENDPOINT_GAP0p18000_DP010",
    "F4_DROP_ENDPOINT_GAP0p26000_DP010",
)
EXPECTED_COUNTS = {
    "total_particles": 83233,
    "fixed_particles": 24161,
    "fluid_particles": 59072,
    "counts_by_source": {"drop": 5824, "pool": 53248},
}
EXPECTED_EXECUTION = {
    "cflnumber": 0.2,
    "CoefDtMin": 0.05,
    "DtIni": 0.0,
    "DtMin": 0.0,
    "DtFixed": 0.0,
    "DtAllParticles": 0.0,
    "TimeMax": 1.2,
    "TimeOut": 0.001,
    "StepAlgorithm": 1,
    "VerletSteps": 40,
    "Kernel": 2,
    "ViscoTreatment": 1,
    "Visco": 0.08,
    "ViscoBoundFactor": 1,
    "DensityDT": 2,
    "DensityDTvalue": 0.1,
    "Shifting": 0,
    "RigidAlgorithm": 1,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.resolve()


def copy_exact(source: Path, destination: Path) -> None:
    """Copy immutable native bytes without replacing an output."""

    require_file(source)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if sha256(source) != sha256(destination):
        raise RuntimeError(f"staged artifact hash mismatch: {source} -> {destination}")


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_int(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not an integer: {value!r}") from exc


def generated_particle_counts(xml_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    """Read actual counts from generated XML, never from stdout or BI4.

    The XML is the all-numeric GenCase product consumed by the 069 actual QA.
    Parsing this ``execution/particles`` section is sufficient to bind the
    runtime fields while keeping this builder away from native particle
    arrays and BI4 decoding.
    """

    root = ET.parse(require_file(xml_path)).getroot()
    particles = root.find("execution/particles")
    if particles is None:
        raise ValueError(f"generated XML lacks execution/particles: {xml_path}")
    fixed = particles.find("fixed")
    fluids = particles.findall("fluid")
    if fixed is None or not fluids:
        raise ValueError(f"generated XML lacks fixed/fluid partition: {xml_path}")
    total = _as_int(particles.attrib["np"], "np")
    fixed_count = _as_int(fixed.attrib["count"], "fixed.count")
    fluid_blocks = [
        {
            "mkfluid": _as_int(node.attrib["mkfluid"], "fluid.mkfluid"),
            "mk": _as_int(node.attrib["mk"], "fluid.mk"),
            "begin": _as_int(node.attrib["begin"], "fluid.begin"),
            "count": _as_int(node.attrib["count"], "fluid.count"),
        }
        for node in fluids
    ]
    fluid_count = sum(row["count"] for row in fluid_blocks)
    if total != fixed_count + fluid_count:
        raise ValueError(
            f"XML particle partition does not close: total={total}, "
            f"fixed={fixed_count}, fluid={fluid_count}"
        )
    if _as_int(particles.attrib.get("nb", fixed_count), "nb") != fixed_count:
        raise ValueError(f"XML fixed count disagrees with nb: {xml_path}")

    source_regions = metadata.get("source_regions")
    expected_sources = metadata.get("expected_counts_by_source")
    if not isinstance(source_regions, dict) or not isinstance(expected_sources, dict):
        raise ValueError(f"metadata lacks source count bindings: {xml_path}")
    by_mkfluid = {row["mkfluid"]: row["count"] for row in fluid_blocks}
    source_counts: dict[str, int] = {}
    for source, region in source_regions.items():
        if not isinstance(region, dict) or "mkfluid" not in region:
            raise ValueError(f"metadata source lacks mkfluid: {source}")
        mkfluid = _as_int(region["mkfluid"], f"{source}.mkfluid")
        if mkfluid not in by_mkfluid:
            raise ValueError(f"generated XML lacks mkfluid={mkfluid} for source={source}")
        observed = by_mkfluid[mkfluid]
        expected = _as_int(expected_sources[source], f"{source}.expected_count")
        if observed != expected:
            raise ValueError(
                f"generated XML source count differs for {source}: "
                f"observed={observed}, expected={expected}"
            )
        source_counts[str(source)] = observed
    return {
        "source": "generated_xml_execution_particles",
        "xml_sha256": sha256(xml_path),
        "total_particles": total,
        "fixed_particles": fixed_count,
        "fluid_particles": fluid_count,
        "fluid_blocks": fluid_blocks,
        "counts_by_source": source_counts,
        "expected_counts_by_source": {
            str(key): _as_int(value, f"{key}.expected_count")
            for key, value in expected_sources.items()
        },
    }


def execution_parameters(xml_path: Path) -> dict[str, float | int]:
    """Extract the mother execution contract for source-only validation."""

    root = ET.parse(require_file(xml_path)).getroot()
    parameters = root.findall("execution/parameters/parameter")
    result: dict[str, float | int] = {}
    for node in parameters:
        key = node.attrib.get("key")
        value = node.attrib.get("value")
        if key is None or value is None:
            raise ValueError(f"malformed execution parameter in {xml_path}")
        number = finite(value)
        if number is None:
            raise ValueError(f"non-numeric execution parameter {key}={value!r}")
        result[key] = int(number) if number.is_integer() else number
    cfl = root.find("execution/constants/cflnumber")
    if cfl is None or finite(cfl.attrib.get("value")) is None:
        raise ValueError(f"generated XML lacks execution/constants/cflnumber: {xml_path}")
    cfl_value = float(cfl.attrib["value"])
    result["cflnumber"] = int(cfl_value) if cfl_value.is_integer() else cfl_value
    return result


def validate_mother_recipe(mother_xml_path: Path, mother_receipt_path: Path) -> dict[str, Any]:
    """Validate exact full-window, no-slip, DT and CFL inheritance."""

    mother_xml = require_file(mother_xml_path)
    mother_receipt = load_json(require_file(mother_receipt_path))
    if mother_receipt.get("status") != "completed" or mother_receipt.get("returncode") != 0:
        raise ValueError("mother qualification receipt is not a completed returncode=0 run")
    request = mother_receipt.get("request")
    if not isinstance(request, dict):
        raise ValueError("mother qualification receipt lacks request")
    request_command = request.get("command")
    if not isinstance(request_command, list) or request_command[-2:] != SOLVER_OPTIONS:
        raise ValueError("mother qualification command does not use -tmax:1.2/-tout:0.001")
    params = execution_parameters(mother_xml)
    for key, expected in EXPECTED_EXECUTION.items():
        observed = params.get(key)
        if observed is None or not math.isclose(float(observed), float(expected), rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"mother execution option drift for {key}: {observed!r} != {expected!r}")
    return {
        "mother_generated_xml": str(mother_xml),
        "mother_generated_xml_sha256": sha256(mother_xml),
        "mother_qualification_receipt": str(mother_receipt_path.resolve()),
        "mother_qualification_receipt_sha256": sha256(mother_receipt_path),
        "solver_executable": str(SOLVER),
        "solver_options": SOLVER_OPTIONS,
        "time_window_s": [0.0, 1.2],
        "output_interval_s": 0.001,
        "expected_frames": 1201,
        "no_slip_boundary_inheritance": {
            "boundary_model": "DBC",
            "ViscoTreatment": params["ViscoTreatment"],
            "Visco": params["Visco"],
            "ViscoBoundFactor": params["ViscoBoundFactor"],
        },
        "dt_cfl_inheritance": {
            "cflnumber": params["cflnumber"],
            "CoefDtMin": params["CoefDtMin"],
            "DtIni": params["DtIni"],
            "DtMin": params["DtMin"],
            "DtFixed": params["DtFixed"],
            "DtAllParticles": params["DtAllParticles"],
        },
        "execution_parameters": params,
        "mutation_boundary": "Only the genuine endpoint native prefix and new solver output path differ from the mother qualification request.",
    }


def endpoint_commands(gencase_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = gencase_result.get("commands")
    if not isinstance(rows, list):
        raise ValueError("063 GenCase result lacks commands list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("endpoint_id"):
            raise ValueError("063 GenCase result contains malformed endpoint command")
        endpoint_id = str(row["endpoint_id"])
        if endpoint_id in result:
            raise ValueError(f"duplicate 063 endpoint command: {endpoint_id}")
        result[endpoint_id] = row
    return result


def validate_original_bindings(
    *,
    plan_path: Path,
    plan: dict[str, Any],
    gencase_result_path: Path,
    gencase_result: dict[str, Any],
    original_receipt_path: Path,
    original_receipt: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if plan.get("stage_contract", {}).get("launch_allowed") is not False:
        raise ValueError("source endpoint plan must keep launch_allowed=false")
    if gencase_result.get("status") != "completed":
        raise ValueError("063 individual GenCase result is not completed")
    if Path(str(gencase_result.get("source_plan", ""))).resolve() != plan_path.resolve():
        raise ValueError("063 GenCase result is not bound to the source endpoint plan")
    if gencase_result.get("source_plan_sha256") != sha256(plan_path):
        raise ValueError("063 GenCase result source-plan hash differs")
    if _as_int(gencase_result.get("gencase_returncode_failures"), "gencase_returncode_failures") != 0:
        raise ValueError("063 individual GenCase result reports a nonzero endpoint")
    if _as_int(gencase_result.get("endpoint_count"), "endpoint_count") != len(EXPECTED_ENDPOINTS):
        raise ValueError("063 GenCase result endpoint count differs from the two physical endpoints")
    if original_receipt.get("status") != "failed":
        raise ValueError("the original 063 shared receipt must remain failed")
    if original_receipt.get("returncode") != 0:
        raise ValueError("the original 063 shared receipt must retain wrapper returncode=0")
    if original_receipt.get("error") != "GenCase actual particle count missing":
        raise ValueError("the original 063 receipt is not the captured-stdout count failure")
    if not require_file(gencase_result_path) or not require_file(original_receipt_path):
        raise FileNotFoundError("063 evidence binding is missing")
    commands = endpoint_commands(gencase_result)
    if set(commands) != set(EXPECTED_ENDPOINTS):
        raise ValueError("063 command endpoint IDs do not preserve the physical endpoint set")
    return commands


def validate_actual_qa(
    *,
    index_path: Path,
    index: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if index.get("schema") != "ds02.f4.drop-gap-initial-native-audit-index.v3":
        raise ValueError("unexpected 069 actual-QA index schema")
    if index.get("status") != "initial-native-input-integrity-pass" or index.get("pass") is not True:
        raise ValueError("069 actual-QA index is not a passing input-integrity result")
    if index.get("launch_allowed") is not False:
        raise ValueError("069 actual-QA index must remain launch_allowed=false")
    if index.get("source_plan_sha256") != sha256(Path(str(index["source_plan"]))):
        raise ValueError("069 actual-QA index source-plan hash does not verify")
    plan_ids = [str(row["endpoint_id"]) for row in plan.get("endpoints", [])]
    if plan_ids != list(EXPECTED_ENDPOINTS):
        raise ValueError("endpoint plan order or IDs drifted")
    rows = index.get("endpoints")
    if not isinstance(rows, list):
        raise ValueError("069 actual-QA index lacks endpoint rows")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("endpoint_id") in result:
            raise ValueError("069 actual-QA index contains malformed or duplicate endpoint")
        endpoint_id = str(row["endpoint_id"])
        if endpoint_id not in EXPECTED_ENDPOINTS:
            raise ValueError(f"unexpected endpoint in 069 actual-QA index: {endpoint_id}")
        checks = row.get("checks")
        if not isinstance(checks, dict) or checks.get("true_3d") is not True or checks.get("gencase_completed") is not True:
            raise ValueError(f"069 actual QA lacks true 3-D completed GenCase checks: {endpoint_id}")
        if row.get("pass") is not True or row.get("native_audit_returncode") != 0:
            raise ValueError(f"069 actual QA endpoint is not a passing audit: {endpoint_id}")
        qa_path = require_file(Path(str(row["initial_qa_json"])))
        if row.get("initial_qa_json_sha256") != sha256(qa_path):
            raise ValueError(f"069 actual QA report hash differs: {endpoint_id}")
        qa = load_json(qa_path)
        qa_checks = qa.get("checks")
        if not isinstance(qa_checks, dict) or qa_checks.get("true_3d") is not True:
            raise ValueError(f"069 endpoint report is not bound to true_3d: {endpoint_id}")
        xml_path = require_file(Path(str(row["derived_generated_xml"])))
        bi4_path = require_file(Path(str(row["derived_generated_bi4"])))
        source_xml_path = require_file(Path(str(row["source_generated_xml"])))
        source_bi4_path = require_file(Path(str(row["source_generated_bi4"])))
        if row.get("derived_generated_xml_sha256") != sha256(xml_path):
            raise ValueError(f"069 derived XML hash differs: {endpoint_id}")
        if row.get("derived_generated_bi4_sha256") != sha256(bi4_path):
            raise ValueError(f"069 derived BI4 hash differs: {endpoint_id}")
        if row.get("source_generated_xml_sha256") != sha256(source_xml_path):
            raise ValueError(f"069 source XML hash differs: {endpoint_id}")
        if row.get("source_generated_bi4_sha256") != sha256(source_bi4_path):
            raise ValueError(f"069 source BI4 hash differs: {endpoint_id}")
        if row.get("derived_generated_xml_sha256") != row.get("source_generated_xml_sha256"):
            raise ValueError(f"069 derived/source XML bytes differ: {endpoint_id}")
        if row.get("derived_generated_bi4_sha256") != row.get("source_generated_bi4_sha256"):
            raise ValueError(f"069 derived/source BI4 bytes differ: {endpoint_id}")
        result[endpoint_id] = {
            "index_row": row,
            "qa_path": qa_path,
            "qa": qa,
            "xml_path": xml_path,
            "bi4_path": bi4_path,
            "source_xml_path": source_xml_path,
            "source_bi4_path": source_bi4_path,
        }
    if set(result) != set(EXPECTED_ENDPOINTS):
        raise ValueError("069 actual-QA index does not contain exactly two endpoints")
    return result


def derived_receipt(
    *,
    endpoint_id: str,
    endpoint: dict[str, Any],
    command: dict[str, Any],
    source_definition_path: Path,
    counts: dict[str, Any],
    staged_xml: Path,
    staged_bi4: Path,
    metadata_path: Path,
    actual_qa_index_path: Path,
    actual_qa_execution_receipt_path: Path,
    source_gencase_result_path: Path,
    original_receipt_path: Path,
    mother_recipe: dict[str, Any],
    mother_xml_path: Path,
    mother_receipt_path: Path,
) -> dict[str, Any]:
    if command.get("executed") is not True or command.get("returncode") != 0:
        raise ValueError(f"063 individual GenCase command did not complete: {endpoint_id}")
    argv = command.get("command")
    if not isinstance(argv, list) or not argv or not all(isinstance(value, str) for value in argv):
        raise ValueError(f"063 individual GenCase command is not a genuine argv list: {endpoint_id}")
    if Path(argv[0]).name != "GenCase_linux64":
        raise ValueError(f"unexpected individual GenCase executable: {argv[0]}")
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "completed",
        "status_semantics": "derived runtime evidence sidecar; not a new GenCase execution receipt",
        "evidence_role": "runtime_compatible_derived_gencase_evidence",
        "derived_from_existing_gencase": True,
        "derived_is_new_gencase_process": False,
        "builder_ran_gencase": False,
        "endpoint_id": endpoint_id,
        "physical_condition_sha256": endpoint["physical_condition_sha256"],
        "individual_gencase_command": argv,
        "individual_gencase_command_sha256": hashlib.sha256(
            json.dumps(argv, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "individual_gencase_source_definition": str(source_definition_path),
        "individual_gencase_source_definition_sha256": sha256(source_definition_path),
        "individual_gencase_executed": True,
        "individual_gencase_returncode": 0,
        "returncode": 0,
        "gencase_returncode": 0,
        "total_particles": counts["total_particles"],
        "fixed_particles": counts["fixed_particles"],
        "fluid_particles": counts["fluid_particles"],
        "solver_dimension_from_gencase": 3,
        "actual_particle_counts": counts,
        "actual_count_source": "069 generated XML execution/particles; not stdout or shared receipt",
        "actual_3d_source": {
            "actual_qa_index": str(actual_qa_index_path),
            "actual_qa_index_sha256": sha256(actual_qa_index_path),
            "actual_qa_execution_receipt": str(actual_qa_execution_receipt_path),
            "actual_qa_execution_receipt_sha256": sha256(actual_qa_execution_receipt_path),
            "checks_true_3d": True,
            "checks_gencase_completed": True,
            "qa_report": str(endpoint["qa_path"]),
            "qa_report_sha256": sha256(endpoint["qa_path"]),
        },
        "generated_xml": str(staged_xml),
        "generated_xml_sha256": sha256(staged_xml),
        "generated_bi4": str(staged_bi4),
        "generated_bi4_sha256": sha256(staged_bi4),
        "source_generated_xml_069": str(endpoint["xml_path"]),
        "source_generated_xml_069_sha256": sha256(endpoint["xml_path"]),
        "source_generated_bi4_069": str(endpoint["bi4_path"]),
        "source_generated_bi4_069_sha256": sha256(endpoint["bi4_path"]),
        "source_gencase_result": str(source_gencase_result_path),
        "source_gencase_result_sha256": sha256(source_gencase_result_path),
        "original_shared_execution_receipt": str(original_receipt_path),
        "original_shared_execution_receipt_sha256": sha256(original_receipt_path),
        "original_shared_execution_receipt_status": "failed",
        "original_shared_execution_receipt_returncode": 0,
        "original_shared_execution_receipt_error": "GenCase actual particle count missing",
        "metadata": str(metadata_path),
        "metadata_sha256": sha256(metadata_path),
        "mother_qualification_receipt": str(mother_receipt_path),
        "mother_qualification_receipt_sha256": sha256(mother_receipt_path),
        "mother_generated_xml": str(mother_xml_path),
        "mother_generated_xml_sha256": sha256(mother_xml_path),
        "inherited_solver_recipe": mother_recipe,
        "claim_boundary": (
            "The 063 individual GenCase command returned zero and the 069 actual QA "
            "verified the exact generated XML. This sidecar carries those facts for "
            "runtime validation; it does not promote the failed 063 shared receipt "
            "or claim a new GenCase process."
        ),
        "read_policy": {
            "generated_xml": True,
            "native_bi4": "exact-byte staging only; builder does not decode BI4",
            "h5": False,
            "particle_arrays": False,
            "csv": False,
            "conversion": False,
            "solver": False,
            "rendering": False,
        },
        "launch_allowed": False,
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "production_approval": "none",
    }


def qualification_request(
    *,
    endpoint_id: str,
    gap_m: float,
    staged_prefix: Path,
    receipt_path: Path,
    receipt: dict[str, Any],
    input_files: list[Path],
    mother_recipe: dict[str, Any],
    worktree_root: Path,
    metadata_path: Path,
) -> dict[str, Any]:
    gap_token = "0180" if math.isclose(gap_m, 0.18) else "0260"
    attempt_id = f"root-stage1-f4-gap{gap_token}-qualification-full1201-065"
    input_files = [require_file(path) for path in input_files]
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F4",
        "case_id": endpoint_id,
        "attempt_id": attempt_id,
        "kind": "qualification",
        "cpu_threads": 4,
        "max_wall_seconds": 600,
        "estimated_peak_gpu_mib": 8192,
        "estimated_storage_bytes": 7516192768,
        "cwd": str(SOLVER.parent),
        "worktree_root": str(worktree_root),
        "command": [str(SOLVER), str(staged_prefix), "{attempt_root}/solver_output", *SOLVER_OPTIONS],
        "gencase_receipt": str(receipt_path),
        "gencase_receipt_sha256": sha256(receipt_path),
        "input_files": [str(path) for path in input_files],
        "input_sha256": {str(path): sha256(path) for path in input_files},
        "launch": False,
        "launch_allowed": False,
        "launch_owner": "root",
        "status": "source_only_disabled",
        "independent_case_count_increment": 0,
        "production_approval": "none",
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "qualification_scope": {
            "mechanism_id": "finite_drop_pool",
            "recipe_id": "F4_finite_drop_pool_native_dbc_verlet_wendland_v1",
            "resolution": "native_dp010",
            "time_window_s": 1.2,
            "output_interval_s": 0.001,
            "expected_frames": 1201,
            "status": "disabled_pending_root_launch",
            "source_metadata": str(metadata_path),
        },
        "scientific_scope": {
            "physical_case_id": metadata_path.stem.removesuffix(".metadata"),
            "physical_binding_sha256": receipt["physical_condition_sha256"],
            "gap_m": gap_m,
            "independent_case_count_increment": 0,
            "original_controls_and_complete_physical_window_retained": True,
            "solver_options_inherited_from_mother": mother_recipe["solver_options"],
            "qualification_status": "unqualified; disabled qualification request; no Q-N or production claim",
            "production_approval": "none",
        },
        "read_policy": {
            "generated_xml": True,
            "native_bi4": "solver input after Root enables request",
            "h5": False,
            "particle_arrays": False,
            "csv": False,
            "conversion": False,
            "rendering": False,
        },
        "claim_boundary": (
            "Disabled source-ready qualification request. It inherits the mother "
            "full 1.2 s / 0.001 s output recipe and only changes the endpoint native "
            "prefix and solver output path; Root must review 069 and explicitly enable launch."
        ),
    }


def run(
    *,
    plan_path: Path,
    actual_qa_index_path: Path,
    gencase_result_path: Path,
    original_receipt_path: Path,
    metadata_root: Path,
    mother_xml_path: Path,
    mother_receipt_path: Path,
    output_root: Path,
    worktree_root: Path | None = None,
    expected_actual_qa_index_sha256: str | None = None,
) -> int:
    plan_path = require_file(plan_path)
    actual_qa_index_path = require_file(actual_qa_index_path)
    actual_qa_execution_receipt_path = require_file(
        actual_qa_index_path.parent.parent / "execution-receipt.json"
    )
    if expected_actual_qa_index_sha256 and sha256(actual_qa_index_path) != expected_actual_qa_index_sha256:
        raise ValueError("069 actual-QA index hash differs from the Root source binding")
    gencase_result_path = require_file(gencase_result_path)
    original_receipt_path = require_file(original_receipt_path)
    metadata_root = require_file(metadata_root) if metadata_root.is_file() else metadata_root.resolve()
    mother_xml_path = require_file(mother_xml_path)
    mother_receipt_path = require_file(mother_receipt_path)
    if output_root.exists():
        raise FileExistsError(f"fresh output scope already exists: {output_root}")
    plan = load_json(plan_path)
    actual_qa_index = load_json(actual_qa_index_path)
    actual_qa_execution_receipt = load_json(actual_qa_execution_receipt_path)
    if actual_qa_execution_receipt.get("status") != "completed" or actual_qa_execution_receipt.get("returncode") != 0:
        raise ValueError("069 actual-QA execution receipt is not completed returncode=0")
    gencase_result = load_json(gencase_result_path)
    original_receipt = load_json(original_receipt_path)
    mother_recipe = validate_mother_recipe(mother_xml_path, mother_receipt_path)
    commands = validate_original_bindings(
        plan=plan,
        plan_path=plan_path,
        gencase_result_path=gencase_result_path,
        gencase_result=gencase_result,
        original_receipt_path=original_receipt_path,
        original_receipt=original_receipt,
    )
    actual_qa = validate_actual_qa(
        index_path=actual_qa_index_path,
        index=actual_qa_index,
        plan=plan,
    )
    plan_endpoints = {str(row["endpoint_id"]): row for row in plan["endpoints"]}
    if set(plan_endpoints) != set(EXPECTED_ENDPOINTS):
        raise ValueError("endpoint plan does not contain exactly the two F4 gap endpoints")

    output_root.mkdir(parents=True, exist_ok=False)
    failure_binding = {
        "schema": FAILURE_SCHEMA,
        "scope_id": plan["scope_id"],
        "new_scope_id": "root_followup_065_stage1_drop_gap_qualification_rebind_v1",
        "original_attempt_id": "root-stage1-f4-gap0180-0260-genuine-gencase-063",
        "gencase_result": str(gencase_result_path),
        "gencase_result_sha256": sha256(gencase_result_path),
        "gencase_result_status": gencase_result.get("status"),
        "original_shared_execution_receipt": str(original_receipt_path),
        "original_shared_execution_receipt_sha256": sha256(original_receipt_path),
        "original_shared_execution_receipt_status": original_receipt.get("status"),
        "original_shared_execution_receipt_returncode": original_receipt.get("returncode"),
        "original_shared_execution_receipt_error": original_receipt.get("error"),
        "failure_preservation": "The 063 shared receipt remains failed; no file in that attempt is modified.",
        "derived_evidence_boundary": "Per-endpoint receipts are runtime-compatible sidecars, not new GenCase process receipts.",
        "actual_count_policy": "derive per endpoint from the 069 generated XML execution/particles only",
        "launch_allowed": False,
    }
    write_json(output_root / "original-063-failure-binding.json", failure_binding)
    write_json(output_root / "solver-recipe-binding.json", mother_recipe)

    if worktree_root is None:
        worktree_root = Path(__file__).resolve().parents[8]
    worktree_root = worktree_root.resolve()
    endpoint_outputs: list[dict[str, Any]] = []
    request_paths: list[str] = []
    for endpoint_id in EXPECTED_ENDPOINTS:
        endpoint = plan_endpoints[endpoint_id]
        command = commands[endpoint_id]
        qa_row = actual_qa[endpoint_id]
        metadata_path = require_file(metadata_root / f"{endpoint_id}.metadata.json")
        metadata = load_json(metadata_path)
        if metadata.get("case_id") != endpoint_id:
            raise ValueError(f"metadata case ID differs: {endpoint_id}")
        if metadata.get("definition_sha256") != command.get("source_definition_sha256"):
            raise ValueError(f"metadata/063 source definition hash differs: {endpoint_id}")
        source_definition_path = require_file(Path(str(command["source_definition"])))
        if sha256(source_definition_path) != command.get("source_definition_sha256"):
            raise ValueError(f"063 source definition hash does not verify: {endpoint_id}")
        if command.get("physical_condition_sha256") != endpoint["physical_condition_sha256"]:
            raise ValueError(f"physical condition digest drift: {endpoint_id}")
        counts = generated_particle_counts(qa_row["xml_path"], metadata)
        endpoint_params = execution_parameters(qa_row["xml_path"])
        for key, expected in EXPECTED_EXECUTION.items():
            observed = endpoint_params.get(key)
            if observed is None or not math.isclose(float(observed), float(expected), rel_tol=0.0, abs_tol=1e-12):
                raise ValueError(f"endpoint execution option drift for {endpoint_id}: {key}={observed!r}")
        source_xml_063 = require_file(Path(str(command["generated_xml"])))
        source_bi4_063 = require_file(Path(str(command["generated_bi4"])))
        if source_xml_063 != qa_row["source_xml_path"] or source_bi4_063 != qa_row["source_bi4_path"]:
            raise ValueError(f"063 command output path differs from 069 QA source binding: {endpoint_id}")
        if command.get("generated_xml_sha256") and command["generated_xml_sha256"] != sha256(source_xml_063):
            raise ValueError(f"063 command XML hash differs: {endpoint_id}")
        if command.get("generated_bi4_sha256") and command["generated_bi4_sha256"] != sha256(source_bi4_063):
            raise ValueError(f"063 command BI4 hash differs: {endpoint_id}")
        for key, expected in EXPECTED_COUNTS.items():
            if key == "counts_by_source":
                if counts[key] != expected:
                    raise ValueError(f"unexpected actual source counts: {endpoint_id}")
            elif counts[key] != expected:
                raise ValueError(f"unexpected actual particle count {key}: {endpoint_id}")
        endpoint_output = output_root / endpoint_id
        staged_prefix = endpoint_output / "derived-gencase" / endpoint_id
        staged_xml = staged_prefix.with_suffix(".xml")
        staged_bi4 = staged_prefix.with_suffix(".bi4")
        copy_exact(qa_row["xml_path"], staged_xml)
        copy_exact(qa_row["bi4_path"], staged_bi4)
        receipt_path = staged_prefix.parent / "execution-receipt.json"
        receipt_endpoint = dict(endpoint)
        receipt_endpoint.update(
            {
                "qa_path": qa_row["qa_path"],
                "xml_path": qa_row["xml_path"],
                "bi4_path": qa_row["bi4_path"],
            }
        )
        receipt = derived_receipt(
            endpoint_id=endpoint_id,
            endpoint=receipt_endpoint,
            command=command,
            source_definition_path=source_definition_path,
            counts=counts,
            staged_xml=staged_xml,
            staged_bi4=staged_bi4,
            metadata_path=metadata_path,
            actual_qa_index_path=actual_qa_index_path,
            actual_qa_execution_receipt_path=actual_qa_execution_receipt_path,
            source_gencase_result_path=gencase_result_path,
            original_receipt_path=original_receipt_path,
            mother_recipe=mother_recipe,
            mother_xml_path=mother_xml_path,
            mother_receipt_path=mother_receipt_path,
        )
        write_json(receipt_path, receipt)
        request_input_files = [
            SOLVER,
            Path(__file__).resolve(),
            plan_path,
            actual_qa_index_path,
            qa_row["qa_path"],
            actual_qa_execution_receipt_path,
            gencase_result_path,
            original_receipt_path,
            metadata_path,
            source_definition_path,
            mother_xml_path,
            mother_receipt_path,
            staged_xml,
            staged_bi4,
            receipt_path,
            output_root / "original-063-failure-binding.json",
            output_root / "solver-recipe-binding.json",
        ]
        request = qualification_request(
            endpoint_id=endpoint_id,
            gap_m=float(endpoint["gap_m"]),
            staged_prefix=staged_prefix,
            receipt_path=receipt_path,
            receipt=receipt,
            input_files=request_input_files,
            mother_recipe=mother_recipe,
            worktree_root=worktree_root,
            metadata_path=metadata_path,
        )
        request_path = output_root / "requests" / f"{endpoint_id}-qualification-request.json"
        write_json(request_path, request)
        request_paths.append(str(request_path))
        endpoint_outputs.append(
            {
                "endpoint_id": endpoint_id,
                "gap_m": endpoint["gap_m"],
                "physical_condition_sha256": endpoint["physical_condition_sha256"],
                "derived_prefix": str(staged_prefix),
                "derived_xml": str(staged_xml),
                "derived_xml_sha256": sha256(staged_xml),
                "derived_bi4": str(staged_bi4),
                "derived_bi4_sha256": sha256(staged_bi4),
                "derived_receipt": str(receipt_path),
                "derived_receipt_sha256": sha256(receipt_path),
                "actual_particle_counts_from_xml": counts,
                "actual_3d": True,
                "qualification_request": str(request_path),
                "qualification_request_sha256": sha256(request_path),
                "launch_allowed": False,
            }
        )

    index = {
        "schema": SCHEMA,
        "family_id": "F4",
        "scope_id": "root_followup_065_stage1_drop_gap_qualification_rebind_v1",
        "upstream_source_scope_id": plan["scope_id"],
        "source_plan": str(plan_path),
        "source_plan_sha256": sha256(plan_path),
        "actual_qa_index": str(actual_qa_index_path),
        "actual_qa_index_sha256": sha256(actual_qa_index_path),
        "actual_qa_execution_receipt": str(actual_qa_execution_receipt_path),
        "actual_qa_execution_receipt_sha256": sha256(actual_qa_execution_receipt_path),
        "gencase_preflight_result": str(gencase_result_path),
        "gencase_preflight_result_sha256": sha256(gencase_result_path),
        "original_shared_execution_receipt": str(original_receipt_path),
        "original_shared_execution_receipt_sha256": sha256(original_receipt_path),
        "original_shared_execution_receipt_status": original_receipt["status"],
        "original_shared_execution_receipt_error": original_receipt["error"],
        "original_063_failure_binding": str(output_root / "original-063-failure-binding.json"),
        "solver_recipe_binding": str(output_root / "solver-recipe-binding.json"),
        "solver_recipe_binding_sha256": sha256(output_root / "solver-recipe-binding.json"),
        "endpoints": endpoint_outputs,
        "request_paths": request_paths,
        "status": "qualification-input-integrity-pass",
        "pass": True,
        "launch_allowed": False,
        "launch_owner": "root",
        "q_n_status": "not_assessed",
        "precision_status": "not_accepted",
        "production_approval": "none",
        "independent_case_count_increment": 0,
        "frame_contract": {
            "time_max_s": 1.2,
            "time_out_s": 0.001,
            "expected_frames": 1201,
        },
        "actual_count_policy": "069 generated XML execution/particles only; 063 individual command returncode retained",
        "claim_boundary": (
            "Source-ready disabled qualification inputs. Runtime-compatible receipt fields "
            "are derived from the genuine 063 individual command, exact generated XML, and "
            "passing 069 true-3-D QA. The failed 063 shared receipt is preserved and no new "
            "GenCase process is claimed."
        ),
        "read_policy": {
            "generated_xml": True,
            "native_bi4": "exact-byte staging only; no decode by this builder",
            "h5": False,
            "particle_arrays": False,
            "csv": False,
            "conversion": False,
            "solver": False,
            "rendering": False,
        },
    }
    write_json(output_root / "qualification-input-binding-index.json", index)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--actual-qa-index", required=True, type=Path)
    parser.add_argument("--gencase-result", required=True, type=Path)
    parser.add_argument("--original-execution-receipt", required=True, type=Path)
    parser.add_argument("--metadata-root", required=True, type=Path)
    parser.add_argument("--mother-xml", required=True, type=Path)
    parser.add_argument("--mother-qualification-receipt", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--worktree-root", type=Path)
    parser.add_argument("--actual-qa-index-sha256")
    args = parser.parse_args()
    return run(
        plan_path=args.plan,
        actual_qa_index_path=args.actual_qa_index,
        gencase_result_path=args.gencase_result,
        original_receipt_path=args.original_execution_receipt,
        metadata_root=args.metadata_root,
        mother_xml_path=args.mother_xml,
        mother_receipt_path=args.mother_qualification_receipt,
        output_root=args.output_root,
        worktree_root=args.worktree_root,
        expected_actual_qa_index_sha256=args.actual_qa_index_sha256,
    )


if __name__ == "__main__":
    raise SystemExit(main())
