#!/usr/bin/env python3
"""Freeze a one-time, static-only F8 Definition/control materialization gate.

This module deliberately writes only its JSON review receipt.  It neither
creates the proposed XML/CSV inputs nor invokes any DualSPHysics executable.
The receipt can authorize exactly one *future* static materialization of those
two inputs, and explicitly leaves CPU preflight to a separate authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001"
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001")
OUTPUT = LAB / ROOT / "definition-control-static-review-v1/review.json"
SCHEMA = "core.cfd.f8.definition_control_static_review.v1"

DOCUMENTS = {
    "scope_ruling": ROOT / "root-scope-ruling-v1/receipt.json",
    "candidate_card": ROOT / "candidate-card-v2.json",
    "parameter_contract": ROOT / "parameter-contract-v1.json",
    "steady_oracle_contract": ROOT / "reference-oracle-v1/contract.json",
    "startup_oracle_contract": ROOT / "reference-oracle-v2/contract.json",
    "observation_parser_contract": ROOT / "observation-parser-v1/contract.json",
}
OFFICIAL_PRECEDENTS = {
    "viscous_channel_geometry": Path(
        "vendor/official/DualSPHysics_v5.4/examples/main/15_Poiseuille/"
        "CasePoiseuille_Def.xml"),
    "acceleration_input_example": Path(
        "vendor/official/DualSPHysics_v5.4/examples/main/04_ExternalForces/"
        "CaseForces_Def.xml"),
    "periodic_boundary_example": Path(
        "vendor/official/DualSPHysics_v5.4/examples/main/02_Periodicity/"
        "CasePeriodicity_Def.xml"),
    "acceleration_input_format": Path(
        "vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML_AccInput.xml"),
    "periodic_mdbc_format": Path(
        "vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML__Parameters.xml"),
}
DEFINITION_TARGET = ROOT / "input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001_Def.xml"
CONTROL_TARGET = ROOT / "input/acceleration/F8_OPC_q0p500_acceleration.csv"
FORBIDDEN_EXECUTION = (
    "gencase_invoked", "native_decode_invoked", "solver_invoked", "gpu_started",
)
MUTATION_CONTROLS = (
    "queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {
        "path": str(relative), "sha256": sha256(path),
        "bytes": path.stat().st_size, "role": role,
    }


def load_documents() -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Load required JSON inputs, returning precise missing/invalid gaps."""
    documents: dict[str, dict[str, Any]] = {}
    gaps: list[dict[str, str]] = []
    for name, relative in DOCUMENTS.items():
        path = LAB / relative
        if not path.is_file():
            gaps.append({"code": "INPUT_MISSING", "input": name, "detail": str(relative)})
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            gaps.append({"code": "INPUT_INVALID_JSON", "input": name, "detail": str(exc)})
            continue
        if not isinstance(value, dict):
            gaps.append({"code": "INPUT_NOT_OBJECT", "input": name, "detail": str(relative)})
            continue
        documents[name] = value
    return documents, gaps


def _controls_are_static_only(controls: Any) -> bool:
    if not isinstance(controls, dict):
        return False
    # Earlier immutable contracts predate some controls (for example the
    # parameter contract has no native-decoder field).  An omitted control is
    # not a runtime grant; every control that a source does declare must still
    # be closed.  This review's own control block enumerates the full set.
    if any(key in controls and controls[key] is not False for key in FORBIDDEN_EXECUTION):
        return False
    return all(key not in controls or controls[key] == 0 for key in MUTATION_CONTROLS)


def evaluate_static_constraints(documents: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Return every closed-gate reason; never turn an incomplete gate into a write grant."""
    gaps: list[dict[str, str]] = []

    def require(code: str, condition: bool, detail: str) -> None:
        if not condition:
            gaps.append({"code": code, "detail": detail})

    ruling = documents.get("scope_ruling", {})
    require("ROOT_SCOPE_RULING", ruling.get("schema") == "core.cfd.f8.root_scope_ruling.v1"
            and ruling.get("scope_id") == SCOPE
            and ruling.get("status") == "accepted_as_distinct_mechanism_family_static_review_only"
            and ruling.get("user_ruling", {}).get("selection") == "mechanism_family_gate"
            and ruling.get("user_ruling", {}).get("inferred") is False,
            "an explicit F8 mechanism-family scope ruling is required")
    require("ROOT_SCOPE_STATIC_ONLY", ruling.get("qualification_claim") == "none"
            and ruling.get("qualification_credit") == 0
            and _controls_are_static_only(ruling.get("execution_controls")),
            "the scope ruling must remain zero-credit and non-executing")

    card = documents.get("candidate_card", {})
    require("CANDIDATE_CARD", card.get("schema") == "core.cfd.f8_oscillatory_body_force_channel_candidate.v2"
            and card.get("scope_id") == SCOPE
            and card.get("mechanism", {}).get("name") == "body-force-driven oscillatory viscous channel",
            "the body-force F8 candidate card v2 must match this scope")
    require("CANDIDATE_SEMANTICS", card.get("qualification_credit") == 0
            and card.get("scientific_status") == "not_executed_not_admitted_zero_credit"
            and card.get("static_contract", {}).get("must_have")
            and _controls_are_static_only(card.get("execution_controls")),
            "candidate semantics must stay static-only and zero-credit")

    parameter = documents.get("parameter_contract", {})
    require("PARAMETER_CONTRACT", parameter.get("schema") == "core.cfd.f8.parameter_contract.v1"
            and parameter.get("scope_id") == SCOPE
            and parameter.get("status") == "pre_admission_static_contract_frozen"
            and parameter.get("admission_granted") is False,
            "the frozen F8 parameter contract is required")
    forcing = parameter.get("forcing_semantics", {})
    require("FORCING_SEMANTICS", forcing.get("globalgravity") == 0
            and forcing.get("native_input") == "accinput linear acceleration ax(t)=A*sin(omega*t) in m/s^2"
            and parameter.get("parameterization", {}).get("zero_mean_control") is True,
            "the future control must be a zero-mean accinput acceleration with global gravity zero")
    require("PARAMETER_STATIC_ONLY", parameter.get("qualification_credit") == 0
            and _controls_are_static_only(parameter.get("execution_controls")),
            "the parameter contract must remain zero-credit and non-executing")

    steady = documents.get("steady_oracle_contract", {})
    startup = documents.get("startup_oracle_contract", {})
    parser = documents.get("observation_parser_contract", {})
    require("STEADY_ORACLE", steady.get("schema") == "core.cfd.f8.reference_oracle_contract.v1"
            and steady.get("scope_id") == SCOPE
            and steady.get("status") == "static_reference_only_no_admission"
            and steady.get("qualification_credit") == 0
            and _controls_are_static_only(steady.get("execution_controls")),
            "the steady Womersley oracle must be static-only and scope-matched")
    require("STARTUP_ORACLE", startup.get("schema") == "core.reference.f8_womersley_oracle.v2_contract.v1"
            and startup.get("scope_id") == SCOPE
            and startup.get("status") == "static_reference_only_no_admission"
            and startup.get("qualification_credit") == 0
            and _controls_are_static_only(startup.get("execution_controls")),
            "the zero-initial-velocity startup oracle must be static-only and scope-matched")
    require("OBSERVATION_PARSER", parser.get("schema") == "core.cfd.f8.observation_parser_contract.v2"
            and parser.get("scope_id") == SCOPE
            and parser.get("status") == "static_parser_only_no_source_present"
            and parser.get("qualification_credit") == 0
            and _controls_are_static_only(parser.get("execution_controls")),
            "the F8 observation parser contract must be static-only and scope-matched")

    for name, relative in OFFICIAL_PRECEDENTS.items():
        require("OFFICIAL_PRECEDENT", (LAB / relative).is_file(),
                f"missing official precedent {name}: {relative}")
    require("FRESH_INPUT_TARGETS", not (LAB / DEFINITION_TARGET).exists()
            and not (LAB / CONTROL_TARGET).exists(),
            "the proposed Definition/control paths must be absent before their one-time materialization")
    return gaps


def build_review() -> dict[str, Any]:
    documents, gaps = load_documents()
    if not gaps:
        gaps.extend(evaluate_static_constraints(documents))
    passed = not gaps
    bindings: list[dict[str, Any]] = []
    for name, relative in DOCUMENTS.items():
        if (LAB / relative).is_file():
            bindings.append(binding(relative, f"F8 static-review input: {name}"))
    for name, relative in OFFICIAL_PRECEDENTS.items():
        if (LAB / relative).is_file():
            bindings.append(binding(relative, f"official F8 XML precedent: {name}"))
    bindings.extend([
        binding(Path("scripts/f8_definition_control_static_review_v1.py"), "review builder"),
        binding(Path("tests/test_f8_definition_control_static_review_v1.py"), "review tests"),
    ])

    return {
        "schema": SCHEMA,
        "scope_id": SCOPE,
        "status": ("static_constraints_satisfied_one_time_definition_control_materialization_authorized"
                   if passed else "static_constraints_unsatisfied_write_not_authorized"),
        "qualification_claim": "none",
        "qualification_credit": 0,
        "static_constraint_gaps": gaps,
        "static_materialization_authorization": {
            "granted": passed,
            "authorization_scope": "one fresh F8 Definition XML and one fresh acceleration CSV only",
            "definition_target": str(DEFINITION_TARGET),
            "control_target": str(CONTROL_TARGET),
            "maximum_fresh_definition_files": 1,
            "maximum_fresh_control_files": 1,
            "reuse_or_overwrite_allowed": False,
            "authorization_consumed": False,
            "explicitly_not_authorized": [
                "GenCase", "native decoder", "solver", "GPU", "queue", "registry", "ledger",
                "denominator mutation", "T1 or T2 qualification", "training",
            ],
        },
        "cpu_preflight_hard_gates": [
            "a separate immutable post-write static review must hash-bind both newly materialized inputs",
            "the Definition must preserve one fluid, zero global gravity, x/y periodicity, fixed no-slip z walls, and no forbidden components",
            "the CSV must be finite, strictly monotonic, cover [0,t_end] without extrapolation, and encode only the registered zero-mean acceleration",
            "the post-write review must verify the parameter contract's fixed geometry, resolution-only dp changes, and every numerical/error gate",
            "a separate CPU-preflight authorization receipt is required before any GenCase, native decoder, solver, queue, or GPU action",
            "any hard-gate failure closes the fixed scope; no threshold relaxation or same-input retry is authorized",
        ],
        "execution_controls": {
            "definition_written": False,
            "control_written": False,
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


def write_review(path: Path) -> dict[str, Any]:
    target = path.resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 static review: {target}")
    review = build_review()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    review = write_review(args.output)
    print(json.dumps({key: review[key] for key in (
        "schema", "status", "qualification_claim", "qualification_credit",
        "static_constraint_gaps", "static_materialization_authorization",
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
