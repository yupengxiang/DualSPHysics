#!/usr/bin/env python3
"""Correct F8 r004's static colocated-control design review without execution.

This is a new immutable review version after r004 static-review-v1 correctly
rejected its own incomplete path replacement.  It retains that zero-execution
rejection and renders a fresh, hash-precommitted r004 input pair in memory.
Only the control location/reference differs from r003: a bare CSV filename
alongside the Definition, as in the official v5.4 single-phase example.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from scripts import f8_r003_static_design_review_v1 as r003
from scripts import f8_r004_static_design_review_v1 as v1


LAB = Path(__file__).resolve().parents[1]
ROOT = v1.ROOT
SCOPE = v1.SCOPE
SCHEMA = "core.cfd.f8.r004_static_design_review.v2"
OUTPUT = LAB / ROOT / "static-design-review-v2/receipt.json"
DEFINITION_TARGET = v1.DEFINITION_TARGET
CONTROL_TARGET = v1.CONTROL_TARGET
PREFLIGHT_ROOT = v1.PREFLIGHT_ROOT
GENERATED_PREFIX = v1.GENERATED_PREFIX
COPIED_CONTROL = v1.COPIED_CONTROL
V1_RECEIPT = ROOT / "static-design-review-v1/receipt.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def binding(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {"path": str(relative), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load_json(relative: Path) -> dict[str, Any]:
    value = json.loads((LAB / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative}")
    return value


def parameters() -> dict[str, float | int]:
    return r003.parameters()


def definition_xml(values: dict[str, float | int]) -> str:
    """Make the exact bare-name replacement, leaving all physics intact."""
    rendered = r003.definition_xml(values)
    replacements = {
        "Proposed F8 r003 static input": "Proposed F8 r004 static input",
        "acceleration/F8_OPC_q0p500_r003_acceleration.csv": v1.control_filename(),
    }
    for old, new in replacements.items():
        if rendered.count(old) != 1:
            raise ValueError(f"r003 renderer no longer has exactly one repair target: {old}")
        rendered = rendered.replace(old, new)
    return rendered


def acceleration_csv(values: dict[str, float | int]) -> str:
    return r003.acceleration_csv(values)


def require(gaps: list[dict[str, str]], code: str, condition: bool, detail: str) -> None:
    if not condition:
        gaps.append({"code": code, "detail": detail})


def evaluate_design(values: dict[str, float | int]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    v1_receipt = load_json(V1_RECEIPT)
    r003_audit = load_json(v1.R003_AUDIT)
    require(gaps, "R004_V1_RETAINED_STATIC_REJECTION",
            v1_receipt.get("schema") == v1.SCHEMA
            and v1_receipt.get("status") == "r004_static_design_review_failed"
            and v1_receipt.get("static_constraint_gaps") == [{"code": "MINIMAL_CONTROL_PATH_REPAIR", "detail": "r004 control must be a bare colocated filename with an unchanged complete table"}]
            and v1_receipt.get("execution_controls", {}).get("gencase_invoked") is False,
            "r004 v1 must remain a zero-execution static rejection")
    require(gaps, "PRIOR_EXECUTION_SCOPES_RETAINED_CLOSED",
            r003_audit.get("status") == "retained_hard_failure_no_retry_zero_credit"
            and "could not be copied" in (LAB / v1.R003_LOG).read_text(encoding="utf-8"),
            "r003's control-copy hard failure must remain immutable evidence")
    require(gaps, "FRESH_R004_INPUT_AND_OUTPUT_NAMESPACES",
            not (LAB / DEFINITION_TARGET).exists() and not (LAB / CONTROL_TARGET).exists()
            and not (LAB / PREFLIGHT_ROOT).exists() and not OUTPUT.exists(),
            "v2 may review only unmaterialized r004 inputs and a new r004 preflight output")
    precedent = v1.official_colocation_proof()
    require(gaps, "OFFICIAL_COLOCATED_CONTROL_PRECEDENT",
            precedent["reference_is_bare_filename"] is True and precedent["control_is_colocated_with_definition"] is True,
            "official v5.4 ExternalForces must show a bare colocated acctimesfile value")
    definition, control = definition_xml(values), acceleration_csv(values)
    constants = {node.tag: dict(node.attrib) for node in ET.fromstring(definition).findall("./casedef/constantsdef/*")}
    required = {"hswl": {"value": "0", "auto": "true"}, "rhopgradient": {"value": "1"}, "gamma": {"value": "7"}, "speedsystem": {"value": "0", "auto": "true"}, "coefsound": {"value": "1"}, "speedsound": {"value": "10", "auto": "false"}}
    require(gaps, "R003_CONSTANTS_AND_PHYSICS_PRESERVED",
            values == r003.parameters() and all(all(constants.get(name, {}).get(key) == item for key, item in attrs.items()) for name, attrs in required.items()),
            "r004 must retain r003's physics and constantsdef compatibility contract")
    require(gaps, "FINITE_Z_WALLS_PRESERVED",
            "<setshapemode>dp | bound</setshapemode>" in definition and "<boxfill>top|bottom</boxfill>" in definition
            and 'name="FiniteNoSlipZWalls"' in definition and 'name="FullyFilledChannelFluid"' in definition,
            "r004 must retain r003's finite z walls")
    require(gaps, "CONTROL_PATH_REPAIRED_TO_OFFICIAL_MODE",
            f'value="{v1.control_filename()}"' in definition and "acceleration/" not in definition
            and control == r003.acceleration_csv(r003.parameters()),
            "r004 must use only the official bare colocated filename with unchanged control values")
    return gaps


def build_review() -> dict[str, Any]:
    values, gaps = parameters(), evaluate_design(parameters())
    definition, control = definition_xml(values).encode("utf-8"), acceleration_csv(values).encode("utf-8")
    return {
        "schema": SCHEMA, "scope_id": SCOPE,
        "status": "r004_static_design_review_v2_passed_inputs_not_authorized" if not gaps else "r004_static_design_review_v2_failed",
        "qualification_claim": "none", "qualification_credit": 0, "static_constraint_gaps": gaps,
        "retained_static_rejection": {"receipt": str(V1_RECEIPT), "status": "r004_static_design_review_failed", "execution_performed": False, "correction": "v2 removes the leftover acceleration/ prefix; v1 is not overwritten"},
        "closed_prior_execution_scopes": [
            {"scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001", "same_input_retry_forbidden": True},
            {"scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002", "same_input_retry_forbidden": True, "r002_output_reuse_forbidden": True},
            {"scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R003", "same_input_retry_forbidden": True, "r003_output_reuse_forbidden": True},
        ],
        "r004_namespace": {"definition_target": str(DEFINITION_TARGET), "control_target": str(CONTROL_TARGET), "preflight_output_root": str(PREFLIGHT_ROOT), "generated_prefix": str(GENERATED_PREFIX), "generated_control_copy": str(COPIED_CONTROL), "all_input_and_preflight_targets_absent_at_review": True},
        "precommitted_input_bytes": {"definition_sha256": sha256_bytes(definition), "definition_bytes": len(definition), "control_sha256": sha256_bytes(control), "control_bytes": len(control), "materialized": False, "future_writer_must_match_exactly": True},
        "minimal_mechanism_repair": {"r003_failed_reference": "acceleration/F8_OPC_q0p500_r003_acceleration.csv", "r004_reference": v1.control_filename(), "r004_source_control": str(CONTROL_TARGET), "change": "remove the child-directory prefix so source CSV is colocated with Definition", "non_changes": ["constantsdef", "hswl", "finite dp | bound z walls", "fluid geometry", "physics parameters", "control table values"], "official_colocation_proof": v1.official_colocation_proof()},
        "control_dependency_copy_proof": {"definition_relative_reference": v1.control_filename(), "source_control": str(CONTROL_TARGET), "required_generated_copy": str(COPIED_CONTROL), "required_copy_hash": sha256_bytes(control), "copy_layout": "source adjacent to Definition; bare filename in acctimesfile; expected generated copy adjacent to generated Definition"},
        "future_cpu_preflight_hard_gates": ["new r004-only authorization binds v2 and both precommitted hashes", "one GenCase maximum in the empty r004 output namespace", "positive fixed boundary count with both z-wall planes", "generated colocated control copy exists and hash-matches before native decode", "any failure closes r004 without retry or r001--r003 output reuse"],
        "next_automatic_step": {"kind": "one-time r004 static input materialization", "requires": ["exclusive creation of exactly the two precommitted colocated inputs", "immutable materialization receipt"], "does_not_authorize": ["GenCase", "native decoder", "solver", "GPU", "queue", "worker", "registry", "ledger", "qualification", "training"]},
        "execution_controls": {"definition_written": False, "control_written": False, "gencase_invoked": False, "native_decode_invoked": False, "solver_invoked": False, "gpu_started": False, "queue_mutation": 0, "worker_started": False, "registry_mutation": 0, "ledger_mutation": 0, "training_started": False},
        "parameters": values,
        "bindings": [
            binding(V1_RECEIPT, "immutable rejected r004 v1 static review"), binding(v1.R003_AUDIT, "immutable closed r003 audit"), binding(v1.R003_LOG, "r003 failed control-copy evidence"),
            binding(Path("scripts/f8_r003_static_design_review_v1.py"), "r003 compatibility renderer"), binding(Path("scripts/f8_r004_static_design_review_v1.py"), "r004 v1 rejected renderer"), binding(Path("scripts/f8_r004_static_design_review_v2.py"), "r004 v2 review builder"), binding(Path("tests/test_f8_r004_static_design_review_v2.py"), "r004 v2 review tests"),
            binding(v1.OFFICIAL_FORCES, "official colocated accel-input Definition precedent"), binding(v1.OFFICIAL_FORCES_DATA_0, "official colocated accel-input CSV precedent"), binding(v1.OFFICIAL_ACCELERATION_FORMAT, "official acceleration format documentation"),
        ],
    }


def write_review(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 r004 static review v2: {target}")
    review = build_review()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    review = write_review(parser.parse_args(argv).output)
    print(json.dumps({key: review[key] for key in ("schema", "status", "qualification_credit", "static_constraint_gaps")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
