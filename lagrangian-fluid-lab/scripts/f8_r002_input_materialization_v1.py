#!/usr/bin/env python3
"""Materialize the one immutable F8 r002 static input pair.

This is the only write step admitted by the F8 r002 static-design review.  It
creates the precommitted Definition and acceleration table with exclusive-create
semantics, then records an immutable receipt.  It cannot invoke GenCase, a
decoder, solver, GPU, queue, worker, registry, ledger, or training path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import f8_r002_static_design_review_v1 as design


LAB = Path(__file__).resolve().parents[1]
ROOT = design.ROOT
SCOPE = design.SCOPE
REVIEW = ROOT / "static-design-review-v1/receipt.json"
DEFINITION_TARGET = design.DEFINITION_TARGET
CONTROL_TARGET = design.CONTROL_TARGET
RECEIPT_TARGET = ROOT / "input-materialization-v1/receipt.json"
SCHEMA = "core.cfd.f8.r002_input_materialization.v1"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def binding(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {
        "path": str(relative),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def load_json(relative: Path) -> dict[str, Any]:
    value = json.loads((LAB / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative}")
    return value


def validate_review(review: dict[str, Any], definition: bytes, control: bytes) -> None:
    committed = review.get("precommitted_input_bytes", {})
    namespace = review.get("r002_namespace", {})
    authorization = review.get("next_authorization_required", {})
    if not (
        review.get("schema") == design.SCHEMA
        and review.get("scope_id") == SCOPE
        and review.get("status") == "r002_static_design_review_passed_inputs_not_authorized"
        and review.get("qualification_claim") == "none"
        and review.get("qualification_credit") == 0
        and review.get("static_constraint_gaps") == []
        and review.get("r001_is_immutable_closed_history", {}).get("same_input_retry_forbidden") is True
        and namespace.get("definition_target") == str(DEFINITION_TARGET)
        and namespace.get("control_target") == str(CONTROL_TARGET)
        and committed.get("materialized") is False
        and committed.get("future_writer_must_match_exactly") is True
        and committed.get("definition_sha256") == sha256_bytes(definition)
        and committed.get("definition_bytes") == len(definition)
        and committed.get("control_sha256") == sha256_bytes(control)
        and committed.get("control_bytes") == len(control)
        and authorization.get("kind") == "one-time r002 static input materialization only"
    ):
        raise PermissionError("F8 r002 review does not bind this exact one-time input materialization")


def ensure_absent(*targets: Path) -> None:
    existing = [str(target) for target in targets if target.exists()]
    if existing:
        raise FileExistsError(
            "refusing one-time F8 r002 materialization because target already exists: "
            + ", ".join(existing)
        )


def finite_wall_proof(definition: str) -> dict[str, Any]:
    values = design.parameters()
    half_height, dp = float(values["half_height"]), float(values["dp"])
    required = (
        "<setshapemode>dp | bound</setshapemode>",
        "<boxfill>top|bottom</boxfill>",
        'name="FiniteNoSlipZWalls"',
        'name="FullyFilledChannelFluid"',
    )
    if not all(fragment in definition for fragment in required):
        raise ValueError("materialized F8 r002 Definition lost the reviewed finite-wall construction")
    if definition.index('name="FiniteNoSlipZWalls"') >= definition.index('name="FullyFilledChannelFluid"'):
        raise ValueError("materialized F8 r002 walls must precede the separate fluid box")
    return {
        "shape_mode": "dp | bound",
        "wall_marker": "FiniteNoSlipZWalls",
        "fluid_marker": "FullyFilledChannelFluid",
        "fluid_z_interval_m": [-half_height, half_height],
        "lower_wall_z_interval_m": [-half_height - dp, -half_height],
        "upper_wall_z_interval_m": [half_height, half_height + dp],
        "static_proof_only": True,
    }


def build_receipt(definition: bytes, control: bytes) -> dict[str, Any]:
    definition_text = definition.decode("utf-8")
    control_text = control.decode("utf-8")
    relative_control = "acceleration/F8_OPC_q0p500_r002_acceleration.csv"
    if f'value="{relative_control}"' not in definition_text:
        raise ValueError("materialized F8 r002 Definition lost its reviewed relative control reference")
    if not control_text.startswith("#Time;LinearAccX;") or not control_text.endswith(";0;0;0;0;0\n"):
        raise ValueError("materialized F8 r002 acceleration table lost reviewed format or endpoint")
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE,
        "status": "one_time_r002_inputs_materialized_static_only",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "r001_is_immutable_closed_history": {
            "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001",
            "same_input_retry_forbidden": True,
            "r001_evidence_mutated": False,
        },
        "authorization": {
            "source": str(REVIEW),
            "consumed": True,
            "overwrite_or_reuse_allowed": False,
            "definition_target": str(DEFINITION_TARGET),
            "control_target": str(CONTROL_TARGET),
        },
        "materialized_inputs": {
            "definition": binding(DEFINITION_TARGET, "precommitted F8 r002 Definition XML"),
            "control": binding(CONTROL_TARGET, "precommitted F8 r002 acceleration CSV"),
            "definition_matches_review_precommit": True,
            "control_matches_review_precommit": True,
        },
        "finite_wall_proof": finite_wall_proof(definition_text),
        "control_dependency_copy_proof": {
            "definition_relative_reference": relative_control,
            "source_control": str(CONTROL_TARGET),
            "required_generated_copy": str(design.COPIED_CONTROL),
            "required_copy_hash": sha256_bytes(control),
            "r001_path_explicitly_forbidden": "acceleration/F8_OPC_q0p500_acceleration.csv",
        },
        "execution_controls": {
            "definition_written": True,
            "control_written": True,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "worker_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "training_started": False,
        },
        "explicitly_not_authorized": [
            "GenCase", "native decoder", "solver", "GPU", "queue", "worker",
            "registry", "ledger", "T1 or T2 qualification", "training",
        ],
        "next_automatic_step": {
            "kind": "one-time F8 r002 CPU-native-preflight authorization and execution",
            "requires": [
                "a new immutable authorization naming this scope and both materialized hashes",
                "a fresh isolated output namespace",
                "one GenCase invocation at most, followed only by declared static/native checks",
            ],
        },
        "bindings": [
            binding(REVIEW, "immutable F8 r002 static design review"),
            binding(Path("scripts/f8_r002_static_design_review_v1.py"), "reviewed in-memory input renderer"),
            binding(Path("scripts/f8_r002_input_materialization_v1.py"), "exclusive-create r002 input materializer"),
            binding(DEFINITION_TARGET, "materialized Definition"),
            binding(CONTROL_TARGET, "materialized acceleration table"),
        ],
    }


def write_materialization(
    definition_target: Path = LAB / DEFINITION_TARGET,
    control_target: Path = LAB / CONTROL_TARGET,
    receipt_target: Path = LAB / RECEIPT_TARGET,
) -> dict[str, Any]:
    registered = (LAB / DEFINITION_TARGET, LAB / CONTROL_TARGET, LAB / RECEIPT_TARGET)
    if (definition_target, control_target, receipt_target) != registered:
        raise ValueError("F8 r002 materializer only permits its registered targets")
    definition = design.definition_xml(design.parameters()).encode("utf-8")
    control = design.acceleration_csv(design.parameters()).encode("utf-8")
    validate_review(load_json(REVIEW), definition, control)
    ensure_absent(definition_target, control_target, receipt_target)
    definition_target.parent.mkdir(parents=True, exist_ok=True)
    control_target.parent.mkdir(parents=True, exist_ok=True)
    receipt_target.parent.mkdir(parents=True, exist_ok=True)
    with definition_target.open("xb") as stream:
        stream.write(definition)
    with control_target.open("xb") as stream:
        stream.write(control)
    receipt = build_receipt(definition, control)
    with receipt_target.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    receipt = write_materialization()
    print(json.dumps({key: receipt[key] for key in ("schema", "status", "qualification_credit", "next_automatic_step")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
