#!/usr/bin/env python3
"""Verify, without executing, the one-time materialized F8 XML/CSV pair.

The v1 review remains historical pre-write authorization.  This v2 review is
the active post-write static acceptance surface and deliberately has no power
to authorize CPU preflight or any runtime activity.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from scripts import f8_input_materialization_v1 as writer


LAB = Path(__file__).resolve().parents[1]
ROOT = writer.ROOT
SCOPE = writer.SCOPE
V1_AUTHORIZATION = writer.AUTHORIZATION
MATERIALIZATION = writer.RECEIPT_TARGET
CONTRACT = writer.CONTRACT
DEFINITION_TARGET = writer.DEFINITION_TARGET
CONTROL_TARGET = writer.CONTROL_TARGET
OUTPUT = LAB / ROOT / "postwrite-static-review-v2/review.json"
SCHEMA = "core.cfd.f8.postwrite_static_review.v2"
DOCUMENTS = {
    "parameter_contract": CONTRACT,
    "steady_oracle_contract": ROOT / "reference-oracle-v1/contract.json",
    "startup_oracle_contract": ROOT / "reference-oracle-v2/contract.json",
    "observation_parser_contract": ROOT / "observation-parser-v1/contract.json",
}
OFFICIAL_PRECEDENTS = {
    "viscous_channel_geometry": Path("vendor/official/DualSPHysics_v5.4/examples/main/15_Poiseuille/CasePoiseuille_Def.xml"),
    "acceleration_input_example": Path("vendor/official/DualSPHysics_v5.4/examples/main/04_ExternalForces/CaseForces_Def.xml"),
    "periodic_boundary_example": Path("vendor/official/DualSPHysics_v5.4/examples/main/02_Periodicity/CasePeriodicity_Def.xml"),
    "acceleration_input_format": Path("vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML_AccInput.xml"),
    "periodic_mdbc_format": Path("vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML__Parameters.xml"),
}
FORBIDDEN_TOKENS = ("free_surface", "floating", "chrono", "motion", "pump", "torque", "material_body")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {"path": str(relative), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load_json(relative: Path) -> dict[str, Any]:
    value = json.loads((LAB / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative}")
    return value


def require(gaps: list[dict[str, str]], code: str, condition: bool, detail: str) -> None:
    if not condition:
        gaps.append({"code": code, "detail": detail})


def _close(a: float, b: float, tolerance: float = 1e-12) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=tolerance)


def validate_v1_authorization(gaps: list[dict[str, str]]) -> None:
    review = load_json(V1_AUTHORIZATION)
    authorization = review.get("static_materialization_authorization", {})
    require(gaps, "V1_AUTHORIZATION", review.get("schema") == "core.cfd.f8.definition_control_static_review.v1"
            and review.get("scope_id") == SCOPE
            and review.get("status") == "static_constraints_satisfied_one_time_definition_control_materialization_authorized"
            and review.get("qualification_credit") == 0
            and authorization.get("granted") is True
            and authorization.get("definition_target") == str(DEFINITION_TARGET)
            and authorization.get("control_target") == str(CONTROL_TARGET),
            "historical v1 authorization must match this exact pair")


def validate_materialization(gaps: list[dict[str, str]], values: dict[str, float | int]) -> None:
    receipt = load_json(MATERIALIZATION)
    controls = receipt.get("execution_controls", {})
    require(gaps, "MATERIALIZATION_RECEIPT", receipt.get("schema") == writer.SCHEMA
            and receipt.get("scope_id") == SCOPE
            and receipt.get("status") == "one_time_inputs_materialized_static_only"
            and receipt.get("qualification_claim") == "none"
            and receipt.get("qualification_credit") == 0
            and receipt.get("authorization", {}).get("consumed") is True
            and receipt.get("authorization", {}).get("overwrite_or_reuse_allowed") is False,
            "one-time materialization receipt must be immutable and zero-credit")
    require(gaps, "MATERIALIZATION_NO_RUNTIME", controls.get("definition_written") is True
            and controls.get("control_written") is True
            and all(controls.get(key) is False for key in ("gencase_invoked", "native_decode_invoked", "solver_invoked", "gpu_started", "training_started"))
            and all(controls.get(key) == 0 for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation")),
            "materialization must have written only the static inputs")
    parameters = receipt.get("parameters", {})
    require(gaps, "MATERIALIZATION_PARAMETERS", all(_close(float(parameters.get(key, math.nan)), float(value))
            for key, value in values.items()), "materialization receipt parameters must match the frozen contract")


def validate_xml(gaps: list[dict[str, str]], values: dict[str, float | int]) -> None:
    path = LAB / DEFINITION_TARGET
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError) as exc:
        gaps.append({"code": "XML_PARSE", "detail": str(exc)})
        return
    tags = {node.tag.lower() for node in root.iter() if isinstance(node.tag, str)}
    require(gaps, "XML_FORBIDDEN_COMPONENT", not any(token in tags for token in FORBIDDEN_TOKENS),
            "Definition must contain no free-surface, floating, Chrono, motion, pump, torque, or material-body component")
    gravity = root.find(".//gravity")
    require(gaps, "XML_GLOBAL_GRAVITY", gravity is not None and all(gravity.attrib.get(axis) == "0" for axis in ("x", "y", "z")),
            "Definition must set global gravity vector to zero")
    require(gaps, "XML_ONE_FLUID", [node.attrib.get("mk") for node in root.findall(".//setmkfluid")] == ["0"],
            "Definition must define exactly one fluid")
    require(gaps, "XML_Z_WALLS", [node.attrib.get("mk") for node in root.findall(".//setmkbound")] == ["0"],
            "Definition must define exactly one fixed wall marker")
    wall_fills = [node.text for node in root.findall(".//drawbox/boxfill")]
    require(gaps, "XML_WALL_GEOMETRY", wall_fills == ["top|bottom", "solid"],
            "Definition must have only z=+/-H walls and one fully-filled fluid box")
    definition = root.find(".//geometry/definition")
    require(gaps, "XML_GEOMETRY", definition is not None and _close(float(definition.attrib.get("dp", "nan")), float(values["dp"]))
            and _close(float(definition.find("pointmin").attrib["z"]), -float(values["half_height"]))
            and _close(float(definition.find("pointmax").attrib["z"]), float(values["half_height"]))
            and _close(float(definition.find("pointmax").attrib["x"]), float(values["length_x"]))
            and _close(float(definition.find("pointmax").attrib["y"]), float(values["length_y"])),
            "Definition geometry must exactly match frozen channel dimensions and production dp")
    parameters = {node.attrib.get("key"): node.attrib.get("value") for node in root.findall(".//parameters/parameter")}
    require(gaps, "XML_MDBC_PERIODIC", parameters.get("Boundary") == "2" and "XYPeriodic" in parameters
            and parameters.get("XYPeriodic") == "0", "Definition must use mDBC and native X/Y periodicity")
    require(gaps, "XML_LAMINAR", parameters.get("ViscoTreatment") == "3"
            and _close(float(parameters.get("Visco", "nan")), float(values["viscosity"])),
            "Definition must retain contract laminar viscosity")
    require(gaps, "XML_TIME_COVERAGE", _close(float(parameters.get("TimeMax", "nan")), float(values["t_end"])),
            "Definition TimeMax must equal the control-table end")
    accinputs = root.findall(".//accinput")
    require(gaps, "XML_ACCINPUT", len(accinputs) == 1 and accinputs[0].attrib == {"mkfluid": "0"}
            and accinputs[0].find("globalgravity").attrib.get("value") == "0"
            and accinputs[0].find("acctimesfile").attrib.get("value") == "acceleration/F8_OPC_q0p500_acceleration.csv",
            "Definition must use one fluid-only accinput pointing to the registered CSV")


def validate_csv(gaps: list[dict[str, str]], values: dict[str, float | int]) -> None:
    path = LAB / CONTROL_TARGET
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.reader(stream, delimiter=";"))
    except OSError as exc:
        gaps.append({"code": "CSV_READ", "detail": str(exc)})
        return
    header = ["#Time", "LinearAccX", "LinearAccY", "LinearAccZ", "AngularAccX", "AngularAccY", "AngularAccZ"]
    require(gaps, "CSV_HEADER", bool(rows) and rows[0] == header, "CSV must use official seven-column accinput format")
    data = rows[1:]
    expected_rows = int(values["total_cycles"]) * int(values["points_per_period"]) + 1
    require(gaps, "CSV_COUNT", len(data) == expected_rows, "CSV must provide 64 intervals per period over the full control window")
    try:
        numeric = [[float(value) for value in row] for row in data]
    except ValueError as exc:
        gaps.append({"code": "CSV_NUMERIC", "detail": str(exc)})
        return
    require(gaps, "CSV_COLUMNS_FINITE", all(len(row) == 7 and all(math.isfinite(value) for value in row) for row in numeric),
            "CSV values must be finite seven-column rows")
    if not numeric:
        return
    times = [row[0] for row in numeric]
    acceleration = [row[1] for row in numeric]
    require(gaps, "CSV_TIME_RANGE", _close(times[0], 0.0) and _close(times[-1], float(values["t_end"]))
            and all(later > earlier for earlier, later in zip(times, times[1:])),
            "CSV time must be strictly increasing and cover [0,t_end]")
    require(gaps, "CSV_X_ONLY", all(value == 0.0 for row in numeric for value in row[2:]),
            "CSV must encode only linear X acceleration")
    require(gaps, "CSV_SINE", all(_close(ax, float(values["amplitude"]) * math.sin(float(values["omega"]) * time_s), 5e-15)
            for time_s, ax in zip(times, acceleration)), "CSV acceleration must equal A*sin(omega*t)")
    require(gaps, "CSV_ZERO_MEAN", abs(sum(acceleration) / len(acceleration)) < 1e-15,
            "complete-period sampled forcing must have zero discrete mean")
    require(gaps, "CSV_OBSERVATION_COVERAGE", float(values["t_end"]) >= float(values["observation_start"])
            + int(values["observation_cycles"]) * float(values["period"]),
            "control must cover the full observation window without extrapolation")


def build_review() -> dict[str, Any]:
    gaps: list[dict[str, str]] = []
    contract = load_json(CONTRACT)
    values = writer.parameters(contract)
    validate_v1_authorization(gaps)
    validate_materialization(gaps, values)
    validate_xml(gaps, values)
    validate_csv(gaps, values)
    bindings = [
        binding(V1_AUTHORIZATION, "historical v1 static authorization"),
        binding(MATERIALIZATION, "one-time input materialization receipt"),
        binding(CONTRACT, "frozen parameter contract"),
        binding(Path("scripts/f8_input_materialization_v1.py"), "one-time input writer"),
        binding(DEFINITION_TARGET, "materialized F8 Definition XML"),
        binding(CONTROL_TARGET, "materialized F8 acceleration CSV"),
        binding(Path("scripts/f8_postwrite_static_review_v2.py"), "post-write static review builder"),
        binding(Path("tests/test_f8_postwrite_static_review_v2.py"), "post-write static review tests"),
    ]
    for name, relative in DOCUMENTS.items():
        bindings.append(binding(relative, f"F8 static contract: {name}"))
    for name, relative in OFFICIAL_PRECEDENTS.items():
        bindings.append(binding(relative, f"official syntax precedent: {name}"))
    passed = not gaps
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE,
        "status": "input_materialized_postwrite_static_verification_passed" if passed else "input_materialized_postwrite_static_verification_failed",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "static_constraint_gaps": gaps,
        "input_materialization": {"definition": str(DEFINITION_TARGET), "control": str(CONTROL_TARGET), "verified": passed},
        "cpu_preflight": {
            "authorized": False,
            "requires_separate_immutable_authorization": True,
            "explicitly_not_authorized": ["GenCase", "native decoder", "solver", "GPU", "queue", "registry", "ledger", "T1/T2 qualification", "training"],
        },
        "execution_controls": {
            "definition_written": True,
            "control_written": True,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "training_started": False,
        },
        "bindings": bindings,
    }


def write_review(path: Path = OUTPUT) -> dict[str, Any]:
    target = path.resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 post-write review: {target}")
    review = build_review()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    review = write_review(args.output)
    print(json.dumps({key: review[key] for key in ("schema", "status", "qualification_claim", "qualification_credit", "static_constraint_gaps")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
