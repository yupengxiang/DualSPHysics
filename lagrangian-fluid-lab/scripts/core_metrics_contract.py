#!/usr/bin/env python3
"""Static Core physical/material metric contract.

This module is intentionally independent of ``core_evaluation``.  It freezes
the additive metric schema and validates deterministic fixtures only; it does
not read simulation data, import a trainer, start a solver/GPU, or write the
registry/ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NAMESPACE = "core-v1/evaluation/physical-material-metrics-contract-v1"
DEFAULT_CONTRACT = LAB_ROOT / "campaigns/core-v1/evaluation/physical-material-metrics-contract-v1/contract.json"
DEFAULT_RECEIPT = LAB_ROOT / "campaigns/core-v1/evaluation/physical-material-metrics-contract-v1/planning-receipt.json"

SCHEMA = "core.evaluator_physical_material_metrics.v1"
RECEIPT_SCHEMA = "core.evaluator_physical_material_metrics.planning_receipt.v1"
FIXTURE_SCHEMA = "core.evaluator_physical_material_metrics.synthetic_fixture.v1"
MASS_CLOSURE_TOLERANCE = 1e-12
UNKNOWN_BOUND = 0.01

METRIC_DEFINITIONS = {
    "kinetic_energy": {
        "kind": "mass_weighted_scalar_time_series",
        "units": "J",
        "formula": "sum_i(0.5 * mass_i * dot(velocity_i, velocity_i))",
        "denominator": "registered future frames, excluding initial state",
        "fixed_denominator": True,
    },
    "geometry_aware_field": {
        "kind": "geometry_sampled_normalized_rmse",
        "units": "dimensionless",
        "formula": "sqrt(sum_q(weight_q * error_q^2) / sum_q(weight_q)) / registered_scale",
        "denominator": "registered geometry elements per future frame",
        "fixed_denominator": True,
    },
    "material_transfer": {
        "kind": "source_mass_partition",
        "units": "mass_fraction",
        "formula": "category_mass / initial_source_mass",
        "denominator": "initial source mass; no survivor renormalization",
        "fixed_denominator": True,
    },
    "first_passage": {
        "kind": "source_particle_first_arrival",
        "units": "s",
        "formula": "first target-entry time; right-censored particles remain in denominator",
        "denominator": "all registered source particles",
        "fixed_denominator": True,
    },
    "residence": {
        "kind": "source_particle_destination_dwell_time",
        "units": "s",
        "formula": "integral of destination membership over the registered window",
        "denominator": "all registered source particles",
        "fixed_denominator": True,
    },
    "return": {
        "kind": "first_passage_then_exit_fraction",
        "units": "fraction",
        "formula": "returned_source_particles / all_registered_source_particles",
        "denominator": "all registered source particles",
        "fixed_denominator": True,
    },
    "unknown_bound": {
        "kind": "unassigned_source_mass_fraction",
        "units": "mass_fraction",
        "formula": "unknown_mass / initial_source_mass",
        "denominator": "initial source mass; no survivor renormalization",
        "bound": UNKNOWN_BOUND,
        "fixed_denominator": True,
    },
}

SOURCE_RELS = (
    "../PLAN.md",
    "scripts/core_metrics_contract.py",
    "scripts/core_evaluation.py",
    "scripts/transport_metrics.py",
)


class MetricsContractError(ValueError):
    """Raised when a metric contract or fixture is malformed."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetricsContractError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise MetricsContractError("JSON root must be an object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_sha256(path: Path, source: Path) -> None:
    path.write_text(f"{sha256_file(source)}  {source.name}\n", encoding="utf-8")


def _ref(path: Path, root: Path) -> dict[str, Any]:
    return {"path": path.resolve().relative_to(root.resolve()).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _integer(value: Any, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MetricsContractError(f"{name} must be an integer")
    if value < (1 if positive else 0):
        raise MetricsContractError(f"{name} must be {'positive' if positive else 'non-negative'}")
    return value


def _real(value: Any, name: str, *, nonnegative: bool = False, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise MetricsContractError(f"{name} must be finite")
    result = float(value)
    if positive and result <= 0:
        raise MetricsContractError(f"{name} must be positive")
    if nonnegative and result < 0:
        raise MetricsContractError(f"{name} must be non-negative")
    return result


def _source_bindings(root: Path) -> list[dict[str, Any]]:
    result = []
    for relative in SOURCE_RELS:
        path = (root / relative).resolve()
        if not path.is_file():
            raise MetricsContractError(f"missing source: {relative}")
        result.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return result


def build_contract(root: str | Path = LAB_ROOT, *, namespace: str = DEFAULT_NAMESPACE) -> dict[str, Any]:
    root = Path(root).resolve()
    return {
        "schema": SCHEMA,
        "namespace": namespace,
        "status": "planning_only",
        "metric_definitions": METRIC_DEFINITIONS,
        "denominator_policy": {
            "frame": "all registered future frames; missing/failed/nonfinite frame is penalty, never dropped",
            "geometry": "all registered geometry elements in every registered future frame",
            "material": "all registered initial source particles and initial source mass",
            "survivor_renormalization": False,
        },
        "failure_policy": {
            "missing": "fail_closed",
            "nan_or_infinite": "fail_closed",
            "early_failure": "fail_closed; retain registered denominator",
            "material_sidecar_missing": "fail_closed; no material metric is evaluable",
            "right_censor": "explicit_negative_result; retain denominator",
        },
        "negative_result_policy": {
            "evaluated_negative_results_are_valid_evidence": True,
            "qualification_claim": "none",
            "credit": 0,
        },
        "compatibility": {
            "existing_formal_score_unchanged": True,
            "existing_score_schema": "core.scoring_protocol.v1",
            "integration": "additive_contract_only",
        },
        "source_closure": {"source_bindings": _source_bindings(root)},
        "execution_policy": {
            "static_only": True,
            "synthetic_fixture_only": True,
            "solver_started": False,
            "gpu_started": False,
            "training_started": False,
            "registry_written": False,
            "ledger_written": False,
        },
    }


def _fixture_gate(fixture: Mapping[str, Any]) -> list[str]:
    execution = fixture.get("execution")
    if not isinstance(execution, Mapping):
        return ["execution_missing"]
    reasons = []
    if execution.get("executed") is not True:
        reasons.append("execution_not_performed")
    if execution.get("early_failure") is True:
        reasons.append("early_failure")
    if execution.get("material_sidecar_present") is not True:
        reasons.append("material_sidecar_missing")
    return reasons


def validate_fixture(fixture: Mapping[str, Any]) -> None:
    """Validate a complete deterministic fixture, rejecting ambiguous data."""
    if not isinstance(fixture, Mapping) or fixture.get("schema") != FIXTURE_SCHEMA:
        raise MetricsContractError("fixture schema mismatch")
    if not isinstance(fixture.get("case_id"), str) or not fixture["case_id"]:
        raise MetricsContractError("case_id is required")
    denominators = fixture.get("denominators")
    if not isinstance(denominators, Mapping):
        raise MetricsContractError("denominators are required")
    frames = _integer(denominators.get("future_frames"), "future_frames", positive=True)
    elements = _integer(denominators.get("geometry_elements"), "geometry_elements", positive=True)
    particles = _integer(denominators.get("source_particles"), "source_particles", positive=True)
    source_mass = _real(denominators.get("source_mass_kg"), "source_mass_kg", positive=True)
    metrics = fixture.get("metrics")
    if not isinstance(metrics, Mapping):
        raise MetricsContractError("metrics are required")

    kinetic = metrics.get("kinetic_energy")
    if not isinstance(kinetic, Mapping) or not isinstance(kinetic.get("values_j"), list) or len(kinetic["values_j"]) != frames:
        raise MetricsContractError("kinetic_energy must cover the fixed frame denominator")
    for index, value in enumerate(kinetic["values_j"]):
        _real(value, f"kinetic_energy.values_j[{index}]", nonnegative=True)

    geometry = metrics.get("geometry_aware_field")
    if not isinstance(geometry, Mapping) or not isinstance(geometry.get("frames"), list) or len(geometry["frames"]) != frames:
        raise MetricsContractError("geometry_aware_field must cover the fixed frame denominator")
    for index, row in enumerate(geometry["frames"]):
        if not isinstance(row, Mapping):
            raise MetricsContractError(f"geometry frame {index} is missing")
        if _integer(row.get("sample_count"), f"geometry frame {index} sample_count", positive=True) != elements:
            raise MetricsContractError("geometry element denominator mismatch")
        _real(row.get("squared_error_sum"), f"geometry frame {index} squared_error_sum", nonnegative=True)
        _real(row.get("weight_sum"), f"geometry frame {index} weight_sum", positive=True)
        _real(row.get("scale"), f"geometry frame {index} scale", positive=True)

    transfer = metrics.get("material_transfer")
    if not isinstance(transfer, Mapping):
        raise MetricsContractError("material_transfer is required")
    if not math.isclose(_real(transfer.get("source_mass_kg"), "transfer source mass", positive=True), source_mass, rel_tol=0, abs_tol=MASS_CLOSURE_TOLERANCE):
        raise MetricsContractError("material source mass denominator mismatch")
    destinations = transfer.get("destination_mass_kg")
    if not isinstance(destinations, Mapping) or not destinations:
        raise MetricsContractError("destination mass partition is required")
    total = 0.0
    for name, value in destinations.items():
        if not isinstance(name, str) or not name:
            raise MetricsContractError("destination names must be non-empty")
        total += _real(value, f"destination {name}", nonnegative=True)
    unknown = _real(transfer.get("unknown_mass_kg"), "unknown_mass_kg", nonnegative=True)
    unclassified = _real(transfer.get("unclassified_mass_kg"), "unclassified_mass_kg", nonnegative=True)
    if not math.isclose(total + unknown + unclassified, source_mass, rel_tol=0, abs_tol=MASS_CLOSURE_TOLERANCE):
        raise MetricsContractError("material mass partition does not close")

    passage = metrics.get("first_passage")
    if not isinstance(passage, Mapping) or not isinstance(passage.get("times_s"), list) or len(passage["times_s"]) != particles:
        raise MetricsContractError("first_passage must cover all source particles")
    censored = 0
    for index, value in enumerate(passage["times_s"]):
        if value is None:
            censored += 1
        else:
            _real(value, f"first_passage.times_s[{index}]", nonnegative=True)
    if _integer(passage.get("right_censored_count"), "right_censored_count") != censored:
        raise MetricsContractError("right-censor count mismatch")

    residence = metrics.get("residence")
    if not isinstance(residence, Mapping) or not isinstance(residence.get("seconds"), list) or len(residence["seconds"]) != particles:
        raise MetricsContractError("residence must cover all source particles")
    for index, value in enumerate(residence["seconds"]):
        _real(value, f"residence.seconds[{index}]", nonnegative=True)

    returned = metrics.get("return")
    if not isinstance(returned, Mapping):
        raise MetricsContractError("return metric is required")
    if _integer(returned.get("eligible_count"), "return eligible_count") != particles:
        raise MetricsContractError("return denominator mismatch")
    if _integer(returned.get("first_passage_count"), "return first_passage_count") != particles - censored:
        raise MetricsContractError("return first-passage count mismatch")
    if _integer(returned.get("returned_count"), "return returned_count") > particles:
        raise MetricsContractError("returned_count exceeds fixed denominator")

    bound = metrics.get("unknown_bound")
    if not isinstance(bound, Mapping):
        raise MetricsContractError("unknown_bound is required")
    if not math.isclose(_real(bound.get("source_mass_kg"), "unknown bound source mass", positive=True), source_mass, rel_tol=0, abs_tol=MASS_CLOSURE_TOLERANCE):
        raise MetricsContractError("unknown bound denominator mismatch")
    if not math.isclose(_real(bound.get("unknown_mass_kg"), "unknown bound mass", nonnegative=True), unknown, rel_tol=0, abs_tol=MASS_CLOSURE_TOLERANCE):
        raise MetricsContractError("unknown bound mass mismatch")


def evaluate_fixture(fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Return a fail-closed synthetic evaluation report with zero credit."""
    if not isinstance(fixture, Mapping):
        return {"status": "rejected", "failure_reasons": ["fixture_not_an_object"], "credit": 0, "qualification_claim": "none"}
    gate_reasons = _fixture_gate(fixture)
    if gate_reasons:
        return {"status": "rejected", "failure_reasons": gate_reasons, "credit": 0, "qualification_claim": "none"}
    try:
        validate_fixture(fixture)
    except MetricsContractError as exc:
        return {"status": "rejected", "failure_reasons": [str(exc)], "credit": 0, "qualification_claim": "none"}
    metrics = fixture["metrics"]
    den = fixture["denominators"]
    source_mass = float(den["source_mass_kg"])
    unknown_fraction = float(metrics["unknown_bound"]["unknown_mass_kg"]) / source_mass
    passage = metrics["first_passage"]["times_s"]
    return {
        "status": "evaluated",
        "case_id": fixture["case_id"],
        "credit": 0,
        "qualification_claim": "none",
        "negative_result": bool(metrics["first_passage"]["right_censored_count"]),
        "fixed_denominators": dict(den),
        "metric_values": {
            "kinetic_energy_mean_j": sum(float(value) for value in metrics["kinetic_energy"]["values_j"]) / len(metrics["kinetic_energy"]["values_j"]),
            "geometry_field_mean_normalized_rmse": sum(math.sqrt(float(row["squared_error_sum"]) / float(row["weight_sum"])) / float(row["scale"]) for row in metrics["geometry_aware_field"]["frames"]) / len(metrics["geometry_aware_field"]["frames"]),
            "material_unknown_fraction": unknown_fraction,
            "first_passage_observed_count": sum(value is not None for value in passage),
            "residence_mean_s": sum(float(value) for value in metrics["residence"]["seconds"]) / len(metrics["residence"]["seconds"]),
            "return_fraction": float(metrics["return"]["returned_count"]) / int(den["source_particles"]),
            "unknown_bound_pass": unknown_fraction <= UNKNOWN_BOUND,
        },
    }


def _synthetic_fixture() -> dict[str, Any]:
    return {
        "schema": FIXTURE_SCHEMA,
        "case_id": "synthetic-core-metrics-001",
        "execution": {"executed": True, "early_failure": False, "material_sidecar_present": True},
        "denominators": {"future_frames": 3, "geometry_elements": 2, "source_particles": 4, "source_mass_kg": 4.0},
        "metrics": {
            "kinetic_energy": {"values_j": [1.0, 1.2, 1.1]},
            "geometry_aware_field": {"frames": [
                {"sample_count": 2, "squared_error_sum": 0.02, "weight_sum": 2.0, "scale": 1.0},
                {"sample_count": 2, "squared_error_sum": 0.08, "weight_sum": 2.0, "scale": 1.0},
                {"sample_count": 2, "squared_error_sum": 0.045, "weight_sum": 2.0, "scale": 1.0},
            ]},
            "material_transfer": {"source_mass_kg": 4.0, "destination_mass_kg": {"target": 2.0}, "unknown_mass_kg": 0.02, "unclassified_mass_kg": 1.98},
            "first_passage": {"times_s": [0.2, 0.3, None, 0.5], "right_censored_count": 1},
            "residence": {"seconds": [0.4, 0.5, 0.0, 0.6]},
            "return": {"eligible_count": 4, "first_passage_count": 3, "returned_count": 1},
            "unknown_bound": {"source_mass_kg": 4.0, "unknown_mass_kg": 0.02},
        },
    }


def build_receipt(contract: Mapping[str, Any], *, contract_path: str | Path, root: str | Path = LAB_ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    contract_path = Path(contract_path).resolve()
    fixture = _synthetic_fixture()
    return {
        "schema": RECEIPT_SCHEMA,
        "namespace": DEFAULT_NAMESPACE,
        "status": "planning_only",
        "planning_only": True,
        "qualification_claim": "none",
        "credit": 0,
        "contract": _ref(contract_path, root),
        "synthetic_fixture_schema": FIXTURE_SCHEMA,
        "synthetic_report": evaluate_fixture(fixture),
        "execution_constraints": {
            "read_only": True, "solver_started": False, "gpu_started": False,
            "training_started": False, "registry_written": False, "ledger_written": False,
        },
        "formal_score_unchanged": True,
        "contract_schema": contract["schema"],
    }


def _sidecar_ok(path: Path) -> bool:
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.is_file():
        return False
    tokens = sidecar.read_text(encoding="utf-8").split()
    return bool(tokens) and tokens[0] == sha256_file(path)


def _diff(expected: Any, actual: Any, path: str = "") -> list[str]:
    if type(expected) is not type(actual):
        return [path or "root"]
    if isinstance(expected, Mapping):
        keys = set(expected) | set(actual)
        return [item for key in sorted(keys, key=str) for item in _diff(expected.get(key), actual.get(key), f"{path}.{key}".strip("."))]
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [path]
        return [item for index, (left, right) in enumerate(zip(expected, actual)) for item in _diff(left, right, f"{path}[{index}]")]
    return [] if expected == actual else [path]


def verify_contract(contract: Mapping[str, Any] | str | Path, *, root: str | Path = LAB_ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    actual = _load_json(contract) if isinstance(contract, (str, Path)) else dict(contract)
    mismatches = _diff(build_contract(root), actual)
    return {"ok": not mismatches, "mismatches": mismatches, "status": "planning_only" if not mismatches else "invalid", "credit": 0}


def verify_receipt(receipt: Mapping[str, Any] | str | Path, *, root: str | Path = LAB_ROOT, contract_path: str | Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    root = Path(root).resolve()
    payload = _load_json(receipt) if isinstance(receipt, (str, Path)) else dict(receipt)
    mismatches: list[str] = []
    if payload.get("schema") != RECEIPT_SCHEMA or payload.get("namespace") != DEFAULT_NAMESPACE:
        mismatches.append("schema_or_namespace")
    for key, expected in (("status", "planning_only"), ("planning_only", True), ("qualification_claim", "none"), ("credit", 0), ("formal_score_unchanged", True)):
        if payload.get(key) != expected:
            mismatches.append(key)
    constraints = payload.get("execution_constraints")
    expected_constraints = {"read_only": True, "solver_started": False, "gpu_started": False, "training_started": False, "registry_written": False, "ledger_written": False}
    if constraints != expected_constraints:
        mismatches.append("execution_constraints")
    contract_ref = payload.get("contract")
    target = Path(contract_path).resolve()
    if not isinstance(contract_ref, Mapping):
        mismatches.append("contract")
    else:
        referenced = Path(str(contract_ref.get("path")))
        if not referenced.is_absolute():
            referenced = root / referenced
        if referenced.resolve() != target:
            mismatches.append("contract.path")
        else:
            if contract_ref.get("bytes") != target.stat().st_size or contract_ref.get("sha256") != sha256_file(target):
                mismatches.append("contract.hash")
            report = verify_contract(target, root=root)
            mismatches.extend(f"contract.{item}" for item in report["mismatches"])
    expected_report = evaluate_fixture(_synthetic_fixture())
    if payload.get("synthetic_report") != expected_report:
        mismatches.append("synthetic_report")
    if isinstance(receipt, (str, Path)) and not _sidecar_ok(Path(receipt)):
        mismatches.append("receipt.sha256_sidecar")
    return {"ok": not mismatches, "mismatches": mismatches, "status": "planning_only" if not mismatches else "invalid", "credit": 0}


def write_bundle(*, root: str | Path = LAB_ROOT, contract_path: str | Path = DEFAULT_CONTRACT, receipt_path: str | Path = DEFAULT_RECEIPT) -> dict[str, Any]:
    root = Path(root).resolve()
    contract_path = Path(contract_path).resolve()
    receipt_path = Path(receipt_path).resolve()
    contract = build_contract(root)
    _write_json(contract_path, contract)
    _write_sha256(contract_path.with_name(contract_path.name + ".sha256"), contract_path)
    receipt = build_receipt(contract, contract_path=contract_path, root=root)
    _write_json(receipt_path, receipt)
    _write_sha256(receipt_path.with_name(receipt_path.name + ".sha256"), receipt_path)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("write", "verify"):
        item = sub.add_parser(command)
        item.add_argument("--root", type=Path, default=LAB_ROOT)
        item.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
        item.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "write":
        receipt = write_bundle(root=args.root, contract_path=args.contract, receipt_path=args.receipt)
        print(json.dumps({"status": receipt["status"], "credit": 0}, sort_keys=True))
        return 0
    report = verify_receipt(args.receipt, root=args.root, contract_path=args.contract)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
