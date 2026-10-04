#!/usr/bin/env python3
"""Validate the fresh066 GenCase/initial-QA source handoff.

The checker reads JSON, XML definitions, and the small request inputs only. It
does not open BI4/CSV/H5 data, run GenCase, invoke PartVTK, or enable a
request. Future receipt and output digests stay null by contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REQUESTS = HERE / "requests"
OWNERS = HERE / "owners"
GENCASE_BINDINGS = HERE / "gencase-bindings"
QA_BINDINGS = HERE / "qa-bindings"

EXPECTED_HEADS = {
    "F1_STAGE1_ECC_H110_DP010",
    "F1_STAGE1_ECC_H130_DP010",
    "F1_FALLBACK_ECC_COARSE",
    "F1_STAGE1_ECC_H190_DP010",
    "F1_STAGE1_DUAL_H220_DP020",
    "F1_STAGE1_DUAL_H260_DP020",
    "F1_FALLBACK_DUAL_COARSE",
    "F1_STAGE1_DUAL_H340_DP020",
}
EXPECTED_VELOCITIES = {(0.1, 0.0, 0.0), (0.2, 0.0, 0.0)}
ARRAY_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".npy", ".npz"}


class ContractError(ValueError):
    pass


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def sha(path: Path) -> str:
    if path.suffix.lower() in ARRAY_SUFFIXES:
        raise ContractError(f"array-bearing input may not be opened: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ContractError(f"cannot hash request input: {path}") from exc
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def check_request_inputs(request: dict[str, Any], label: str) -> None:
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    require(isinstance(files, list) and isinstance(hashes, dict), f"{label}: request input closure missing")
    require(set(files) == set(hashes), f"{label}: input hash keys differ from input_files")
    for raw in files:
        path = Path(raw)
        require(path.suffix.lower() not in ARRAY_SUFFIXES, f"{label}: array input is bound: {path}")
        require(path.is_file(), f"{label}: missing source input: {path}")
        require(hashes[raw] == sha(path), f"{label}: stale source input hash: {path}")


def check_future_fields(request: dict[str, Any], label: str) -> None:
    require(request.get("future_input_sha256") is None, f"{label}: future input digest is not null")
    future = request.get("future_outputs")
    if isinstance(future, dict):
        require(future.get("sha256") is None, f"{label}: future output digest is not null")
        require(future.get("status") == "not_generated", f"{label}: future output status changed")
    for key, value in request.items():
        if key.endswith("_receipt_sha256") or key in {"gencase_receipt_sha256", "qa_receipt_sha256"}:
            require(value is None, f"{label}: future receipt digest is not null: {key}")


def check_definition(path: Path, velocity: tuple[float, float, float], label: str) -> None:
    require(path.is_file(), f"{label}: definition missing: {path}")
    require(path.read_text(encoding="utf-8").count("<initials>") == 1, f"{label}: initials block count is not one")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ContractError(f"{label}: invalid XML definition: {path}") from exc
    nodes = root.findall(".//initials/velocity")
    require(len(nodes) == 1, f"{label}: expected one direct initials velocity")
    node = nodes[0]
    require(node.get("mkfluid") == "0", f"{label}: velocity Mk is not 0")
    actual = tuple(float(node.get(axis, "nan")) for axis in ("x", "y", "z"))
    require(actual == velocity, f"{label}: XML velocity {actual} != {velocity}")


def check_case(case_id: str) -> dict[str, Any]:
    owner_path = OWNERS / f"{case_id}.owner.json"
    gencase_binding_path = GENCASE_BINDINGS / f"{case_id}.json"
    qa_binding_path = QA_BINDINGS / f"{case_id}.json"
    gencase_request_path = REQUESTS / f"{case_id}.gencase.request.json"
    qa_request_path = REQUESTS / f"{case_id}.initial-qa.request.json"
    owner = load(owner_path)
    gencase_binding = load(gencase_binding_path)
    qa_binding = load(qa_binding_path)
    gencase_request = load(gencase_request_path)
    qa_request = load(qa_request_path)

    label = case_id
    require(owner.get("source_only") is True and owner.get("launch_allowed") is False, f"{label}: owner enabled")
    require(owner.get("execution_allowed") is False, f"{label}: owner execution enabled")
    require(owner.get("independent_case_count_increment") == 0, f"{label}: count increment changed")
    parent = owner.get("parent_case_id")
    require(parent in EXPECTED_HEADS, f"{label}: parent is outside first8")
    velocity = tuple(float(x) for x in owner["axis"]["velocity_m_per_s"])
    require(velocity in EXPECTED_VELOCITIES, f"{label}: velocity is not .1/.2: {velocity}")
    physical = owner["physical_binding"]
    require(owner.get("physical_condition_sha256") == canonical(physical), f"{label}: physical hash mismatch")
    require(physical["initial_state"]["velocities_m_per_s"]["fluid"] == list(velocity), f"{label}: binding velocity mismatch")
    reference = owner.get("parent_actual_voxelization_reference", {})
    require(reference.get("dimension") == 3, f"{label}: parent dimension is not 3D")
    require(int(reference.get("total_particles", 0)) > 0 and int(reference.get("fluid_particles", 0)) > 0, f"{label}: nonpositive parent counts")
    require(float(owner["physical_binding"]["initial_state"]["continuum_mass_by_source_kg"]["fluid"]) > 0, f"{label}: nonpositive source mass")

    definition = Path(gencase_binding["definition"])
    check_definition(definition, velocity, label)
    require(gencase_binding["definition_sha256"] == sha(definition), f"{label}: definition hash mismatch")
    require(gencase_binding.get("initial_velocity_m_per_s") == list(velocity), f"{label}: GenCase velocity mismatch")
    require(gencase_binding.get("new_output_status") == "not_generated", f"{label}: GenCase output is claimed generated")

    for request, task, path in ((gencase_request, "gencase", gencase_request_path), (qa_request, "audit", qa_request_path)):
        require(request.get("schema") == "ds02.runner-request.v2", f"{label}: request schema mismatch: {path.name}")
        require(request.get("case_id") == case_id, f"{label}: request case mismatch: {path.name}")
        require(request.get("kind") == "cpu", f"{label}: request kind mismatch: {path.name}")
        require(request.get("cpu_task_kind") == task, f"{label}: request task mismatch: {path.name}")
        require(request.get("launch_allowed") is False and request.get("execution_allowed") is False, f"{label}: request enabled: {path.name}")
        require(request.get("source_only") is True, f"{label}: request is not source-only: {path.name}")
        require(request.get("independent_case_count_increment") == 0, f"{label}: request count increment changed")
        check_request_inputs(request, label)
        check_future_fields(request, label)
        require("root_followup_064" not in json.dumps(request), f"{label}: stale fresh064 path remains")
        require("-064" not in json.dumps(request), f"{label}: stale -064 attempt remains")

    qa_cases = qa_binding.get("cases", [])
    require(len(qa_cases) == 1 and qa_cases[0].get("case_id") == case_id, f"{label}: QA binding case mismatch")
    qa_case = qa_cases[0]
    require(tuple(float(x) for x in qa_case["expected_velocity_m_per_s"]) == velocity, f"{label}: QA velocity mismatch")
    require(qa_case.get("prospective_output_not_generated") is True, f"{label}: QA output claimed generated")
    require(Path(qa_binding["worker"]).resolve() == (HERE / "qa_initial_vx.py").resolve(), f"{label}: QA worker not rebound")

    return {
        "case_id": case_id,
        "parent_case_id": parent,
        "physical_case_id": owner["physical_case_id"],
        "physical_condition_sha256": owner["physical_condition_sha256"],
        "velocity_m_per_s": list(velocity),
        "parent_total_particles": reference["total_particles"],
        "parent_fluid_particles": reference["fluid_particles"],
        "parent_actual_3d": True,
        "gencase_request": str(gencase_request_path),
        "initial_qa_request": str(qa_request_path),
        "future_receipt_sha256": None,
        "future_output_sha256": None,
        "launch_allowed": False,
    }


def run() -> dict[str, Any]:
    cases = sorted(path.name.removesuffix(".gencase.request.json") for path in REQUESTS.glob("*.gencase.request.json"))
    require(len(cases) == 16, f"expected 16 first8 velocity cases, found {len(cases)}")
    require(len(list(REQUESTS.glob("*.initial-qa.request.json"))) == 16, "expected 16 QA requests")
    require(not list(REQUESTS.glob("*.native.request.json")), "native solver requests must not be part of this handoff")
    results = [check_case(case_id) for case_id in cases]
    require({item["parent_case_id"] for item in results} == EXPECTED_HEADS, "first8 head coverage is incomplete")
    require(len({item["physical_condition_sha256"] for item in results}) == 16, "velocity cases are not independent")
    return {
        "schema": "ds02.f1.initial-vx-gencase-qa-source-validation.v1",
        "handoff_id": "root_followup_066_f1_initial_vx_gencase_qa_v1",
        "family_id": "F1",
        "source_only": True,
        "launch_allowed": False,
        "execution_allowed": False,
        "gencase_launched": False,
        "initial_qa_launched": False,
        "solver_launched": False,
        "raw_arrays_read": False,
        "raw_arrays_hashed": False,
        "shared_index_or_ledger_modified": False,
        "independent_case_count_increment": 0,
        "first8_parent_head_count": 8,
        "case_count": len(results),
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run()
    except ContractError as exc:
        parser.error(str(exc))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
