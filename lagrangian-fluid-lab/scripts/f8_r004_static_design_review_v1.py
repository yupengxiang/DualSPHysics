#!/usr/bin/env python3
"""Freeze the F8 r004 colocated-control repair without executing it.

The r001--r003 preflights are closed, immutable historical scopes.  r004 is
an independent static-only scope.  It preserves r003's native-compatible
constants, fully-filled finite z-wall construction, and physics point while
making the single minimal mechanism change evidenced by the official v5.4
single-phase ExternalForces case: the ``acctimesfile`` value is a bare
filename and its CSV is colocated with the Definition presented to GenCase.

This module renders future bytes only in memory.  It does not create inputs or
run GenCase, a decoder, solver, GPU, queue, or worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from scripts import f8_r003_static_design_review_v1 as r003


LAB = Path(__file__).resolve().parents[1]
R001_ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001")
R002_ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r002")
R003_ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r003")
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r004")
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R004"
SCHEMA = "core.cfd.f8.r004_static_design_review.v1"
OUTPUT = LAB / ROOT / "static-design-review-v1/receipt.json"
DEFINITION_TARGET = ROOT / "input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R004_Def.xml"
# GenCase receives the Definition with its parent as cwd.  The control must be
# alongside it, matching the official single-phase ExternalForces layout.
CONTROL_TARGET = ROOT / "input/F8_OPC_q0p500_r004_acceleration.csv"
PREFLIGHT_ROOT = ROOT / "cpu-native-preflight-v1"
GENERATED_PREFIX = PREFLIGHT_ROOT / "generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R004"
COPIED_CONTROL = PREFLIGHT_ROOT / "generated/F8_OPC_q0p500_r004_acceleration.csv"

R001_AUDIT = R001_ROOT / "cpu-native-preflight-postrun-audit-v1/receipt.json"
R002_PREFLIGHT = R002_ROOT / "cpu-native-preflight-v1/receipt.json"
R003_AUDIT = R003_ROOT / "cpu-native-preflight-postrun-audit-v1/receipt.json"
R003_LOG = R003_ROOT / "cpu-native-preflight-v1/gencase.stdout.log"
OFFICIAL_FORCES = Path("vendor/official/DualSPHysics_v5.4/examples/main/04_ExternalForces/CaseForces_Def.xml")
OFFICIAL_FORCES_DATA_0 = Path("vendor/official/DualSPHysics_v5.4/examples/main/04_ExternalForces/CaseForcesData_0.csv")
OFFICIAL_ACCELERATION_FORMAT = Path("vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML_AccInput.xml")


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
    """Reuse r003's registered physics point verbatim."""
    return r003.parameters()


def control_filename() -> str:
    return "F8_OPC_q0p500_r004_acceleration.csv"


def definition_xml(values: dict[str, float | int]) -> str:
    """Render the r003-compatible Definition with only scope/control repair."""
    rendered = r003.definition_xml(values)
    replacements = {
        "Proposed F8 r003 static input": "Proposed F8 r004 static input",
        "F8_OPC_q0p500_r003_acceleration.csv": control_filename(),
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


def official_colocation_proof() -> dict[str, Any]:
    case = ET.parse(LAB / OFFICIAL_FORCES).getroot()
    refs = [node.attrib.get("value", "") for node in case.findall(".//acctimesfile")]
    return {
        "definition": str(OFFICIAL_FORCES),
        "control": str(OFFICIAL_FORCES_DATA_0),
        "official_reference": "CaseForcesData_0.csv",
        "reference_is_bare_filename": refs[:1] == ["CaseForcesData_0.csv"],
        "control_is_colocated_with_definition": (LAB / OFFICIAL_FORCES).parent == (LAB / OFFICIAL_FORCES_DATA_0).parent,
        "format_document": str(OFFICIAL_ACCELERATION_FORMAT),
        "inference": "Use the official colocated bare-filename mode because r003's child-directory reference emitted one GenCase copy warning.",
    }


def evaluate_design(values: dict[str, float | int]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    r001, r002, r003_audit = load_json(R001_AUDIT), load_json(R002_PREFLIGHT), load_json(R003_AUDIT)
    require(gaps, "PRIOR_SCOPES_RETAINED_CLOSED",
            r001.get("status") == "retained_hard_failure_no_retry_zero_credit"
            and r002.get("status") == "cpu_gencase_or_control_copy_failed_hard_audit"
            and r003_audit.get("status") == "retained_hard_failure_no_retry_zero_credit",
            "r001--r003 must remain immutable closed histories")
    require(gaps, "R003_FAILURE_EVIDENCE",
            "could not be copied" in (LAB / R003_LOG).read_text(encoding="utf-8"),
            "r003 log must retain the single failed child-directory control-copy warning")
    require(gaps, "FRESH_R004_NAMESPACE",
            SCOPE not in {"F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001", "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002", "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R003"}
            and not (LAB / DEFINITION_TARGET).exists() and not (LAB / CONTROL_TARGET).exists()
            and not (LAB / PREFLIGHT_ROOT).exists() and not OUTPUT.exists(),
            "r004 inputs, review, and preflight output must be entirely new")
    precedent = official_colocation_proof()
    require(gaps, "OFFICIAL_COLOCATED_CONTROL_PRECEDENT",
            (LAB / OFFICIAL_FORCES).is_file() and (LAB / OFFICIAL_FORCES_DATA_0).is_file()
            and (LAB / OFFICIAL_ACCELERATION_FORMAT).is_file()
            and precedent["reference_is_bare_filename"] is True
            and precedent["control_is_colocated_with_definition"] is True,
            "official v5.4 ExternalForces must prove bare colocated acctimesfile layout")
    definition, control = definition_xml(values), acceleration_csv(values)
    root = ET.fromstring(definition)
    constants = {node.tag: dict(node.attrib) for node in root.findall("./casedef/constantsdef/*")}
    expected_constants = {
        "gravity": {"x": "0", "y": "0", "z": "0"}, "rhop0": {"value": "1000"},
        "rhopgradient": {"value": "1"}, "hswl": {"value": "0", "auto": "true"},
        "gamma": {"value": "7"}, "speedsystem": {"value": "0", "auto": "true"},
        "coefsound": {"value": "1"}, "speedsound": {"value": "10", "auto": "false"},
        "coefh": {"value": "1.0"}, "cflnumber": {"value": "0.2"},
    }
    require(gaps, "R003_CONSTANTS_AND_PHYSICS_PRESERVED",
            all(all(constants.get(name, {}).get(key) == expected for key, expected in attrs.items()) for name, attrs in expected_constants.items())
            and values == r003.parameters(),
            "r004 must preserve r003 constantsdef and the registered physical point")
    require(gaps, "FINITE_Z_WALLS_PRESERVED",
            "<setshapemode>dp | bound</setshapemode>" in definition
            and "<boxfill>top|bottom</boxfill>" in definition
            and 'name="FiniteNoSlipZWalls"' in definition and 'name="FullyFilledChannelFluid"' in definition,
            "r004 must preserve the proven finite z-wall construction")
    require(gaps, "MINIMAL_CONTROL_PATH_REPAIR",
            f'value="{control_filename()}"' in definition and "acceleration/" not in definition
            and control.startswith("#Time;LinearAccX;") and control.endswith(";0;0;0;0;0\n"),
            "r004 control must be a bare colocated filename with an unchanged complete table")
    return gaps


def build_review() -> dict[str, Any]:
    values, gaps = parameters(), evaluate_design(parameters())
    definition, control = definition_xml(values).encode("utf-8"), acceleration_csv(values).encode("utf-8")
    return {
        "schema": SCHEMA, "scope_id": SCOPE,
        "status": "r004_static_design_review_passed_inputs_not_authorized" if not gaps else "r004_static_design_review_failed",
        "qualification_claim": "none", "qualification_credit": 0, "static_constraint_gaps": gaps,
        "closed_prior_scopes": [
            {"scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001", "same_input_retry_forbidden": True},
            {"scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002", "same_input_retry_forbidden": True, "r002_output_reuse_forbidden": True},
            {"scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R003", "same_input_retry_forbidden": True, "r003_output_reuse_forbidden": True,
             "failure": "GenCase succeeded but rejected the child-directory acceleration control copy"},
        ],
        "r004_namespace": {"definition_target": str(DEFINITION_TARGET), "control_target": str(CONTROL_TARGET),
                           "preflight_output_root": str(PREFLIGHT_ROOT), "generated_prefix": str(GENERATED_PREFIX),
                           "generated_control_copy": str(COPIED_CONTROL), "all_targets_absent_at_review": True},
        "precommitted_input_bytes": {"definition_sha256": sha256_bytes(definition), "definition_bytes": len(definition),
                                      "control_sha256": sha256_bytes(control), "control_bytes": len(control),
                                      "materialized": False, "future_writer_must_match_exactly": True},
        "minimal_mechanism_repair": {
            "r003_failed_reference": "acceleration/F8_OPC_q0p500_r003_acceleration.csv",
            "r004_reference": control_filename(), "r004_source_control": str(CONTROL_TARGET),
            "change": "replace only the child-directory reference and source layout with the official colocated bare-filename mode",
            "non_changes": ["constantsdef compatibility fields", "hswl value=0 auto=true", "finite dp | bound z walls", "fluid geometry", "physics parameters", "control table values"],
            "official_colocation_proof": official_colocation_proof(),
        },
        "finite_wall_proof": {"shape_mode": "dp | bound", "wall_constructor": "drawbox boxfill=top|bottom",
                               "wall_marker": "FiniteNoSlipZWalls", "fluid_marker": "FullyFilledChannelFluid",
                               "claim": "static construction proof only; native realization remains untested in r004"},
        "control_dependency_copy_proof": {"definition_relative_reference": control_filename(), "source_control": str(CONTROL_TARGET),
                                            "required_generated_copy": str(COPIED_CONTROL), "required_copy_hash": sha256_bytes(control),
                                            "copy_layout": "source adjacent to Definition; bare filename in acctimesfile; generated copy adjacent to generated Definition",
                                            "r001_r002_r003_paths_explicitly_forbidden": ["acceleration/F8_OPC_q0p500_acceleration.csv", "acceleration/F8_OPC_q0p500_r002_acceleration.csv", "acceleration/F8_OPC_q0p500_r003_acceleration.csv"]},
        "future_cpu_preflight_hard_gates": ["new r004-only authorization must bind both precommitted hashes and this review", "GenCase may be invoked at most once in the new r004 output namespace", "generated fixed boundary count must be positive with both z-wall planes", "generated control copy adjacent to the generated Definition must exist and hash-match before native decode", "any failure closes r004 with no same-input retry or r001--r003 output reuse"],
        "next_automatic_step": {"kind": "one-time r004 static input materialization", "requires": ["exclusive creation of the two precommitted colocated input bytes", "immutable materialization receipt"], "does_not_authorize": ["GenCase", "native decoder", "solver", "GPU", "queue", "worker", "registry", "ledger", "qualification", "training"]},
        "execution_controls": {"definition_written": False, "control_written": False, "gencase_invoked": False, "native_decode_invoked": False, "solver_invoked": False, "gpu_started": False, "queue_mutation": 0, "worker_started": False, "registry_mutation": 0, "ledger_mutation": 0, "training_started": False},
        "parameters": values,
        "bindings": [
            binding(R001_AUDIT, "immutable closed r001 audit"), binding(R002_PREFLIGHT, "immutable closed r002 receipt"),
            binding(R003_AUDIT, "immutable closed r003 audit"), binding(R003_LOG, "r003 control-copy failure evidence"),
            binding(Path("scripts/f8_r003_static_design_review_v1.py"), "r003 compatibility-preserving renderer"),
            binding(Path("scripts/f8_r004_static_design_review_v1.py"), "r004 static design review builder"),
            binding(Path("tests/test_f8_r004_static_design_review_v1.py"), "r004 static design review tests"),
            binding(OFFICIAL_FORCES, "official colocated accel-input Definition precedent"), binding(OFFICIAL_FORCES_DATA_0, "official colocated accel-input CSV precedent"),
            binding(OFFICIAL_ACCELERATION_FORMAT, "official acceleration-input format documentation"),
        ],
    }


def write_review(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 r004 static review: {target}")
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
