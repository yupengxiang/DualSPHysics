#!/usr/bin/env python3
"""Materialize and run one fresh F6 v10 matrix-cell native preflight.

The command is deliberately one-cell and one-shot.  It reads the frozen
13+2 design, writes a new Definition/XML contract for the selected cell, and
may invoke CPU GenCase and the native decoder once.  It never starts a solver,
GPU process, queue job, registry update, ledger update, or qualification
matrix submission.  A cell's old v10 canary is hash-only context and is never
used as an input.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f6_physical_anchor_cpu_native_preflight_v1 as runner  # noqa: E402
from scripts import f6_physical_anchor_observation_axis_v10_cpu_preflight as base  # noqa: E402


DESIGN_DIR = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-design-20260921"
)
DESIGN_PATH = DESIGN_DIR / "design.json"
ADMISSION_PATH = DESIGN_DIR / "root-admission.json"
PREFLIGHT_ROOT = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-preflight-v4-20260921"
)
CONTEXT_PROPOSAL = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-root-review-20260921/proposal.json"
)
CONTEXT_CANARY = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-20260921/"
    "attempt-001/execution-receipt.json"
)
SCRIPT = Path(__file__).resolve()

TANK_SIZE = (1.50, 0.60, 0.90)
TANK_LOW = (0.0, 0.0, 0.0)
FLUID_LOW = (0.175, 0.05, 0.04)
FLUID_SIZE = (1.14, 0.465, 0.24)
BODY_SIZE = (0.20, 0.16, 0.12)
BODY_COM_XY = (0.75, 0.30)
RHO_FLUID = 1000.0
RHO_BODY = 780.0
GRAVITY = (0.0, 0.0, -9.81)
MKBOUND = 8
TIME_START = 0.0
TIME_END = 1.5
OBSERVATION = (1.0, 1.5)
SCOPE_ID = "F6_fluid_rigid_body_physical_anchor_aligned_sampling_v3"
REVISION_ID = "F6_observation_axis_13plus2_v4"
SCHEMA = "core.f6.observation_axis.cell_preflight.v1"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def bind(path: Path, role: str, *, hash_only: bool = False) -> dict[str, Any]:
    path = path.resolve()
    try:
        display = path.relative_to(LAB.resolve()).as_posix()
    except ValueError:
        display = str(path)
    return {"path": display, "sha256": sha256(path), "bytes": path.stat().st_size, "role": role, "hash_only": hash_only}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def cell_from_design(cell_id: str | None, index: int | None) -> dict[str, Any]:
    design = load(DESIGN_PATH)
    if design.get("status") != "root_review_only_not_submitted":
        raise ValueError("F6 v10 design is not root-review-only")
    if design.get("matrix_cell_count") != 15 or design.get("qualification_credit") != 0 or design.get("T1") is not False:
        raise ValueError("F6 v10 design count/credit guard failed")
    admission = load(ADMISSION_PATH)
    if admission.get("status") != "admitted_for_fresh_native_preflight_only":
        raise ValueError("root admission does not allow fresh preflight")
    cells = design["cells"]
    selected = None
    if cell_id is not None:
        selected = next((item for item in cells if item.get("cell_id") == cell_id), None)
    elif index is not None:
        if index < 0 or index >= len(cells):
            raise ValueError("cell index outside the 15-cell design")
        selected = cells[index]
    if selected is None:
        raise ValueError("provide --cell-id or --index for exactly one cell")
    if selected.get("qualification_only") is not True or selected.get("T1") is not False or selected.get("qualification_credit") != 0:
        raise ValueError("selected cell is not qualification-only")
    return selected


def configure(cell: dict[str, Any], source: Path, output: Path) -> dict[str, Any]:
    q = float(cell["parameter"]["q"])
    dp = float(cell["resolution"]["dp_m"])
    variant = str(cell["design_cell"])
    out = float(cell["time_contract"]["output_interval_s"])
    max_gap = float(cell["time_contract"]["max_native_gap_s"])
    overshoot = float(cell["time_contract"]["terminal_overshoot_max_s"])
    cfl = float(cell["time_contract"]["cfl"])
    body_z = float(cell["parameter"]["value_m"])
    identity = str(cell["cell_id"])
    definition_id = f"CORE_{identity}_FRESH_Definition"
    body_id = f"F6_physical_anchor_body_{identity}"
    case_id = f"{identity}_native_preflight"
    auth_id = f"{identity}_authorization"

    # Bind all mutable constants used by the reviewed CPU/native implementation
    # to this cell.  Each CLI invocation has a fresh process; no cell state is
    # carried across invocations.
    base.DEFINITION_ID = definition_id
    base.BODY_ID = body_id
    base.CASE_ID = case_id
    base.AUTHORIZATION_ID = auth_id
    base.REVISION_ID = REVISION_ID
    base.SCOPE_ID = SCOPE_ID
    base.DP_M = dp
    base.OUTPUT_INTERVAL_S = out
    base.TIME_START_S = TIME_START
    base.TIME_END_S = TIME_END
    base.OBSERVATION_START_S, base.OBSERVATION_END_S = OBSERVATION
    base.BODY_COM = (*BODY_COM_XY, body_z)
    base.TANK_LOW = TANK_LOW
    base.TANK_SIZE = TANK_SIZE
    base.FLUID_LOW = FLUID_LOW
    base.FLUID_SIZE = FLUID_SIZE
    base.BODY_SIZE = BODY_SIZE
    base.RHO_FLUID = RHO_FLUID
    base.RHO_BODY = RHO_BODY
    base.GRAVITY = GRAVITY
    base.MKBOUND = MKBOUND
    base.SOURCE_DIR = source
    base.OUTPUT_DIR = output
    base.SOURCE_PROPOSAL = source / "proposal.json"
    base.SCRIPT = SCRIPT
    base.PROPOSAL = CONTEXT_PROPOSAL

    runner.DEFINITION_ID = definition_id
    runner.BODY_ID = body_id
    runner.CASE_ID = case_id
    runner.AUTHORIZATION_ID = auth_id
    runner.SCOPE_ID = SCOPE_ID
    runner.OUTPUT_DIR = output
    runner.SOURCE_DIR = source
    runner.DEFINITION = source / f"{definition_id}_Def.xml"
    runner.CONTRACT = source / "definition-contract.json"
    runner.SIDECAR = source / "body-state-force-torque-sidecar-schema.json"
    runner.EVENT = source / "event-window-contract.json"
    runner.STATIC_PREFLIGHT = source / "preflight-static.json"
    runner.PROPOSAL = source / "proposal.json"
    runner.PREFLIGHT_SCHEMA = SCHEMA
    runner.physical.IDENTITY = definition_id
    runner.physical.BODY_ID = body_id
    runner.physical.MKBOUND = MKBOUND
    runner.physical.DP_M = dp
    runner.physical.GRAVITY = GRAVITY
    runner.physical.OUTPUT_INTERVAL_S = out
    runner.physical.TIME_START_S = TIME_START
    runner.physical.TIME_END_S = TIME_END
    runner.physical.SIDECAR_SCHEMA = base.SIDECAR_SCHEMA
    runner.physical.EVENT_SCHEMA = base.EVENT_SCHEMA
    return {
        "cell_id": identity,
        "definition_id": definition_id,
        "body_id": body_id,
        "case_id": case_id,
        "authorization_id": auth_id,
        "q": q,
        "dp_m": dp,
        "body_com_z_m": body_z,
        "variant": variant,
        "output_interval_s": out,
        "max_gap_s": max_gap,
        "terminal_overshoot_max_s": overshoot,
        "cfl": cfl,
        "expected_frame_count": int(cell["time_contract"]["expected_frame_count"]),
    }


def patch_definition(path: Path, c: dict[str, Any]) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    cfl = root.find("./casedef/constantsdef/cflnumber")
    if cfl is None:
        raise ValueError("fresh Definition has no cflnumber")
    cfl.set("value", str(c["cfl"]))
    params = {node.get("key"): node for node in root.findall("./execution/parameters/parameter")}
    params["TimeMax"].set("value", str(TIME_END))
    params["TimeOut"].set("value", str(c["output_interval_s"]))
    if c["variant"] == "internal_time":
        for key, value in (("DtIni", 0.0001), ("DtMin", 0.000005), ("DtFixed", 0.0)):
            params[key].set("value", str(value))
    else:
        for key in ("DtIni", "DtMin", "DtFixed"):
            params[key].set("value", "0")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def make_event() -> dict[str, Any]:
    event = base.event_contract()
    event["time_axis_contract"]["max_gap_s"] = CURRENT["max_gap_s"]
    event["time_axis_contract"]["terminal_coverage"]["terminal_overshoot_max_s"] = CURRENT["terminal_overshoot_max_s"]
    event["window"]["expected_frame_count"] = CURRENT["expected_frame_count"]
    event["completion_rule"][0] = f"all {CURRENT['expected_frame_count']} frames exist on the solver-reported actual TimeStep axis"
    event["cell_binding"] = CURRENT
    return event


def make_sidecar(event_path: str) -> dict[str, Any]:
    sidecar = base.sidecar_contract(event_path)
    sidecar["time_axis_contract"]["max_gap_s"] = CURRENT["max_gap_s"]
    sidecar["time_axis_contract"]["terminal_overshoot_max_s"] = CURRENT["terminal_overshoot_max_s"]
    sidecar["time_axis_contract"]["expected_frame_count"] = CURRENT["expected_frame_count"]
    sidecar["cell_binding"] = CURRENT
    return sidecar


def make_proposal(cell: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "core.f6.observation_axis.cell_proposal.v1",
        "proposal_id": f"{c['cell_id']}_fresh_preflight",
        "created_at_utc": stamp(),
        "status": "cell_root_review_fresh_native_preflight_pending",
        "family": "F6",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "cell_id": c["cell_id"],
        "parameter": cell["parameter"],
        "resolution": cell["resolution"],
        "design_cell": c["variant"],
        "qualification_only": True,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "fresh_identity": {
            "definition_id": c["definition_id"],
            "case_id": c["case_id"],
            "body_id": c["body_id"],
            "fresh_generated_xml_required": True,
            "fresh_generated_bi4_required": True,
            "old_v10_canary_reused_as_input": False,
        },
        "root_review_decision": {
            "cpu_native_preflight_authorized": True,
            "solver_canary_authorized_now": False,
            "qualification_claim": "none",
            "qualification_credit": 0,
            "T1": False,
        },
        "context_hash_only": bind(CONTEXT_CANARY, "old v10 canary context only", hash_only=True),
    }


def static_receipt(definition: Path, contract: dict[str, Any], sidecar: dict[str, Any], event: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    root = ET.parse(definition).getroot()
    checks: dict[str, bool] = {}
    text = definition.read_text(encoding="utf-8")
    checks["fresh_xml_case"] = root.tag == "case"
    checks["no_legacy_input"] = not any(token in text for token in ("F6_floating_box", "F6_heavy_box_entry", "F6_twin_floaters", ".bi4", ".h5"))
    gravity = root.find("./casedef/constantsdef/gravity")
    checks["gravity"] = gravity is not None and [float(gravity.get(axis)) for axis in "xyz"] == list(GRAVITY)
    geometry = root.find("./casedef/geometry/definition")
    checks["dp"] = geometry is not None and math.isclose(float(geometry.get("dp")), c["dp_m"], rel_tol=0.0, abs_tol=1e-12)
    checks["body_identity"] = contract.get("body", {}).get("body_id") == c["body_id"]
    checks["event_identity"] = event.get("body_id") == c["body_id"] and event.get("window", {}).get("expected_frame_count") == c["expected_frame_count"]
    checks["time_axis"] = event.get("time_axis_contract", {}).get("max_gap_s") == c["max_gap_s"] and event.get("time_axis_contract", {}).get("native_time_axis") == "solver_reported_actual_TimeStep"
    checks["observation_no_equilibrium"] = event.get("observation_window", {}).get("requires_equilibrium_claim") is False and event.get("observation_window", {}).get("equilibrium_status") == "not_claimed"
    checks["sidecar"] = sidecar.get("body_id") == c["body_id"] and len(sidecar.get("required_fields", [])) == 13
    checks["qualification_guard"] = contract.get("qualification_claim") == "none" and contract.get("qualification_credit") == 0
    checks["execution_closed"] = contract.get("execution_controls", {}).get("solver_invoked") is False and contract.get("execution_controls", {}).get("gpu_invoked") is False
    passed = all(checks.values())
    return {
        "schema": "core.f6.observation_axis.cell_static_preflight.v1",
        # Keep the reviewed runner's admission token while retaining the
        # cell-specific schema and binding below.
        "status": "cpu_physical_anchor_preflight_pass" if passed else "cpu_physical_anchor_preflight_failed",
        "cell_static_status": "cell_static_preflight_pass" if passed else "cell_static_preflight_failed",
        "gate_passed": passed,
        "cell_binding": c,
        "checks": checks,
        "qualification_only": True,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "solver_canary_authorized_in_this_receipt": False,
        "execution_controls": {
            "definition_written": True,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
        },
    }


def dynamic_validate(contract: dict[str, Any], sidecar: dict[str, Any], event: dict[str, Any], static: dict[str, Any]) -> dict[str, Any]:
    root = ET.parse(runner.DEFINITION).getroot()
    params = {node.get("key"): node.get("value") for node in root.findall("./execution/parameters/parameter")}
    checks = {
        "xml_root_case": root.tag == "case",
        "fresh_xml_no_legacy_input": not any(token in runner.DEFINITION.read_text(encoding="utf-8") for token in ("F6_floating_box", "F6_heavy_box_entry", "F6_twin_floaters", ".bi4", ".h5")),
        "gravity_exact": [float(root.find("./casedef/constantsdef/gravity").get(axis)) for axis in "xyz"] == list(GRAVITY),
        "dp_exact": math.isclose(float(root.find("./casedef/geometry/definition").get("dp")), CURRENT["dp_m"], rel_tol=0.0, abs_tol=1e-12),
        "runtime_cadence": params.get("TimeMax") == str(TIME_END) and params.get("TimeOut") == str(CURRENT["output_interval_s"]),
        "event_contract": event.get("window", {}).get("expected_frame_count") == CURRENT["expected_frame_count"] and event.get("time_axis_contract", {}).get("max_gap_s") == CURRENT["max_gap_s"],
        "sidecar_contract": sidecar.get("body_id") == CURRENT["body_id"],
        "static_pass": static.get("gate_passed") is True,
    }
    if not all(checks.values()):
        raise ValueError(f"cell Definition contract failed: {checks}")
    return {"checks": checks, "runtime_parameters": params, "event_window_complete": False, "runtime_sidecar_present": False}


def prepare(cell: dict[str, Any], c: dict[str, Any], source: Path, output: Path) -> dict[str, Any]:
    source.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    definition = source / f"{c['definition_id']}_Def.xml"
    base.write_definition(definition)
    patch_definition(definition, c)
    event = make_event()
    event_path = source / "event-window-contract.json"
    write_json(event_path, event)
    sidecar_path = source / "body-state-force-torque-sidecar-schema.json"
    sidecar = make_sidecar(event_path.relative_to(LAB).as_posix())
    write_json(sidecar_path, sidecar)
    proposal = make_proposal(cell, c)
    proposal_path = source / "proposal.json"
    write_json(proposal_path, proposal)
    contract = base.definition_contract(definition, sidecar_path, event_path)
    contract["contract_id"] = f"{c['cell_id']}_definition_contract"
    contract["case_id"] = c["definition_id"]
    contract["revision_id"] = REVISION_ID
    contract["scope_id"] = SCOPE_ID
    contract["body_id"] = c["body_id"]
    contract["input_binding"]["case_id"] = c["case_id"]
    contract["input_binding"]["definition_id"] = c["definition_id"]
    contract["input_binding"]["fresh_generated_xml_required"] = True
    contract["input_binding"]["fresh_generated_bi4_required"] = True
    contract["time_axis_contract"]["max_gap_s"] = c["max_gap_s"]
    contract["time_axis_contract"]["terminal_overshoot_max_s"] = c["terminal_overshoot_max_s"]
    contract["time_axis_contract"]["expected_frame_count"] = c["expected_frame_count"]
    contract["cell_binding"] = c
    contract_path = source / "definition-contract.json"
    write_json(contract_path, contract)
    static = static_receipt(definition, contract, sidecar, event, c)
    static_path = source / "preflight-static.json"
    write_json(static_path, static)
    return {"definition": definition, "event": event_path, "sidecar": sidecar_path, "contract": contract_path, "static": static_path, "proposal": proposal_path, "static_receipt": static}


def enrich(receipt: dict[str, Any], cell: dict[str, Any], c: dict[str, Any], paths: dict[str, Any]) -> dict[str, Any]:
    generated_xml = receipt.get("gencase_generated_xml") or receipt.get("gencase", {}).get("generated_xml")
    native_bi4 = receipt.get("native_bi4") or receipt.get("gencase", {}).get("native_bi4")
    receipt["schema"] = SCHEMA
    receipt["receipt_id"] = f"{c['cell_id']}_preflight_receipt"
    receipt["scope_id"] = SCOPE_ID
    receipt["revision_id"] = REVISION_ID
    receipt["cell_binding"] = c
    receipt["design_cell"] = cell["design_cell"]
    receipt["qualification_only"] = True
    receipt["qualification_claim"] = "none"
    receipt["qualification_credit"] = 0
    receipt["T1"] = False
    receipt["fresh_identity"] = {
        "definition_id": c["definition_id"],
        "case_id": c["case_id"],
        "body_id": c["body_id"],
        "checks": {
            "definition_filename": paths["definition"].name.startswith(c["definition_id"]),
            "generated_xml_filename": bool(generated_xml and Path(generated_xml["path"]).name.startswith(c["case_id"])),
            "generated_bi4_filename": bool(native_bi4 and Path(native_bi4["path"]).name.startswith(c["case_id"])),
        },
    }
    receipt["input_hashes"] = {
        name: bind(path, f"fresh F6 v10 cell {name}")
        for name, path in {
            "definition": paths["definition"],
            "definition_contract": paths["contract"],
            "sidecar_schema": paths["sidecar"],
            "event_window_contract": paths["event"],
            "proposal": paths["proposal"],
            "static_preflight": paths["static"],
            "design": DESIGN_PATH,
            "root_admission": ADMISSION_PATH,
        }.items()
    }
    if generated_xml:
        receipt["input_hashes"]["generated_xml"] = generated_xml
    if native_bi4:
        receipt["input_hashes"]["generated_bi4"] = native_bi4
    receipt["event_window"] = {
        "status": "auditable_prediction_pending_runtime_event_window",
        "complete": False,
        "observation_window_s": list(OBSERVATION),
        "requires_equilibrium_claim": False,
        "equilibrium_status": "not_claimed",
        "native_time_axis": "solver_reported_actual_TimeStep",
        "expected_frame_count": c["expected_frame_count"],
        "max_gap_s": c["max_gap_s"],
        "terminal_overshoot_max_s": c["terminal_overshoot_max_s"],
    }
    receipt["execution_profile"] = {"model": "gpt-5.6-luna", "reasoning": "max"}
    receipt["execution_controls"].update({"solver_invoked": False, "gpu_invoked": False, "job_created": False, "queue_mutation": 0, "registry_mutation": 0, "ledger_mutation": 0, "matrix_submission": False, "qualification_credit": 0})
    return receipt


CURRENT: dict[str, Any] = {}


def run_cell(cell: dict[str, Any]) -> dict[str, Any]:
    global CURRENT
    cell_id = str(cell["cell_id"])
    index = next(i for i, row in enumerate(load(DESIGN_PATH)["cells"]) if row["cell_id"] == cell_id)
    source = PREFLIGHT_ROOT / f"cell-{index:02d}" / "source"
    output = PREFLIGHT_ROOT / f"cell-{index:02d}" / "native"
    if source.exists() or output.exists():
        raise RuntimeError(f"cell {cell_id} already materialized; same-input retry is disabled")
    CURRENT = configure(cell, source, output)
    paths = prepare(cell, CURRENT, source, output)
    if not paths["static_receipt"]["gate_passed"]:
        raise RuntimeError(f"cell static preflight failed: {paths['static_receipt']['checks']}")
    runner.validate_definition = dynamic_validate
    receipt = runner.run(output)
    receipt = enrich(receipt, cell, CURRENT, paths)
    write_json(output / "preflight.json", receipt)
    runner.verify_receipt(output / "preflight.json")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell-id")
    parser.add_argument("--index", type=int)
    args = parser.parse_args(argv)
    cell = cell_from_design(args.cell_id, args.index)
    try:
        receipt = run_cell(cell)
    except Exception as error:
        print(json.dumps({"status": "cell_preflight_not_started", "cell_id": cell.get("cell_id"), "error": repr(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": receipt.get("status"), "cell_id": cell["cell_id"], "preflight_pass": receipt.get("preflight_pass", False), "output": str((PREFLIGHT_ROOT / f"cell-{next(i for i, row in enumerate(load(DESIGN_PATH)['cells']) if row['cell_id'] == cell['cell_id'] )}/native/preflight.json").resolve())}, ensure_ascii=False))
    return 0 if receipt.get("status") == "cpu_native_preflight_pass_exact_one" else 1


if __name__ == "__main__":
    raise SystemExit(main())
