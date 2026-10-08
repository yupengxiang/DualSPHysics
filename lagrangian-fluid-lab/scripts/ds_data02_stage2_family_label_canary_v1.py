#!/usr/bin/env python3
"""Run one source-bound, finite-region label canary for a CURRENT case.

The canary consumes an already completed typed trajectory.  It does not run a
solver, alter a raw tree, or infer physical fate from an unclassified/native
identity loss.  Every source join is checked against the immutable CURRENT
entry before the native saved-frame label engine is allowed to read the H5.

The command is deliberately a forward-only wrapper around
``ds_data02_native_labels.materialize``.  It writes a new HDF5 and report
under the runner's ``{attempt_root}``; historical label attempts are never
selected as output targets.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
STAGE2_ROOT = LAB_ROOT / "campaigns/ds-data-02/stage2"
sys.path.insert(0, str(LAB_ROOT / "scripts"))

from ds_data02_native_labels import materialize  # noqa: E402


SCHEMA = "ds02.stage2.family-label-canary.v1"
FAMILIES = {f"F{i}" for i in range(1, 8)}


class ContractError(ValueError):
    """Raised when a source-bound canary contract is unsafe or incomplete."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{label} must be a non-empty path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ContractError(f"{label} is not a file: {path}")
    return path


def _sha_binding(value: Any, label: str) -> tuple[Path, str]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a path/sha256 object")
    path = _path(value.get("path"), label + ".path")
    expected = value.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ContractError(f"{label}.sha256 must be a 64-character digest")
    return path, expected


def _check_digest(path: Path, expected: str, label: str) -> None:
    actual = sha256_file(path)
    if actual != expected:
        raise ContractError(f"{label} digest mismatch: {path}")


def _source_bindings(contract: dict[str, Any]) -> list[tuple[str, Path, str]]:
    source = contract.get("source")
    if not isinstance(source, dict):
        raise ContractError("source object is required")
    required = (
        "current_manifest",
        "trajectory",
        "conversion_report",
        "generated_xml",
        "gencase_receipt",
        "solver_receipt",
        "run_out",
        "run_parts",
    )
    result: list[tuple[str, Path, str]] = []
    for key in required:
        path, expected = _sha_binding(source.get(key), "source." + key)
        result.append((key, path, expected))
    label_config = contract.get("label_config")
    path, expected = _sha_binding(label_config, "label_config")
    result.append(("label_config", path, expected))
    return result


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError(f"{label} must contain a JSON object")
    return value


def _find_current_case(current: dict[str, Any], physical_case_id: str) -> dict[str, Any]:
    rows = [row for row in current.get("cases", [])
            if isinstance(row, dict) and row.get("physical_case_id") == physical_case_id]
    if len(rows) != 1:
        raise ContractError(f"CURRENT must contain exactly one {physical_case_id!r}, got {len(rows)}")
    return rows[0]


def _assert_same_path(actual: Any, expected: Path, label: str) -> None:
    if not isinstance(actual, str) or Path(actual).expanduser().resolve() != expected:
        raise ContractError(f"{label} does not bind the selected source: {actual!r} != {str(expected)!r}")


def _assert_receipt_completed(path: Path, label: str) -> None:
    receipt = _load_json(path, label)
    status = receipt.get("status")
    if status is not None and status not in {"completed", "passed", "success"}:
        raise ContractError(f"{label} is not completed: status={status!r}")


def validate_contract(contract: dict[str, Any], *, check_content: bool = True) -> dict[str, Any]:
    """Validate the exact CURRENT/trajectory/config/raw-log join.

    ``check_content=False`` is used only by manufactured tests to exercise
    contract identity checks without opening a large source.  A real run
    always keeps the default content check and rechecks every registered
    source digest, including the typed trajectory.
    """
    if contract.get("schema") != SCHEMA:
        raise ContractError("unsupported canary contract schema")
    family = contract.get("family_id")
    if family not in FAMILIES:
        raise ContractError("family_id must be F1..F7")
    physical = contract.get("physical_case_id")
    if not isinstance(physical, str) or not physical:
        raise ContractError("physical_case_id is required")
    if not isinstance(contract.get("mechanism_id"), str) or not contract["mechanism_id"]:
        raise ContractError("mechanism_id is required")
    bindings = _source_bindings(contract)
    by_key = {key: (path, expected) for key, path, expected in bindings}
    if check_content:
        for key, path, expected in bindings:
            _check_digest(path, expected, "source." + key if key != "label_config" else key)

    current_path, _ = by_key["current_manifest"]
    current = _load_json(current_path, "CURRENT manifest")
    row = _find_current_case(current, physical)
    if row.get("family_id") != family:
        raise ContractError("CURRENT family differs from contract family")

    trajectory_path, trajectory_expected = by_key["trajectory"]
    trajectory = row.get("trajectory")
    if not isinstance(trajectory, dict):
        raise ContractError("CURRENT trajectory entry is missing")
    _assert_same_path(trajectory.get("path"), trajectory_path, "CURRENT trajectory path")
    producer_sha = trajectory.get("producer_declared_sha256")
    if producer_sha != trajectory_expected:
        raise ContractError("trajectory digest is not the CURRENT producer-declared digest")
    if row.get("frames") != contract.get("frames") or row.get("particles") != contract.get("particles"):
        raise ContractError("CURRENT frame/identity counts differ from contract")
    if row.get("actual_time_window_s") != contract.get("actual_time_window_s"):
        raise ContractError("CURRENT actual time window differs from contract")

    conversion_path, _ = by_key["conversion_report"]
    conversion = row.get("conversion_report")
    if not isinstance(conversion, dict):
        raise ContractError("CURRENT conversion report entry is missing")
    _assert_same_path(conversion.get("path"), conversion_path, "CURRENT conversion report path")

    source_bindings = row.get("source_bindings")
    if not isinstance(source_bindings, dict):
        raise ContractError("CURRENT source_bindings is missing")
    for key in ("generated_xml", "gencase_receipt", "solver_receipt"):
        path, expected = by_key[key]
        binding = source_bindings.get(key)
        if not isinstance(binding, dict):
            raise ContractError(f"CURRENT source binding is missing: {key}")
        _assert_same_path(binding.get("path"), path, "CURRENT " + key + " path")
        if binding.get("sha256") != expected:
            raise ContractError("CURRENT source binding digest differs: " + key)

    raw_root = row.get("raw_root", {}).get("path") if isinstance(row.get("raw_root"), dict) else None
    if not isinstance(raw_root, str):
        raise ContractError("CURRENT raw_root.path is missing")
    solver_dir = Path(raw_root).expanduser().resolve().parent
    if by_key["run_out"][0].parent != solver_dir or by_key["run_parts"][0].parent != solver_dir:
        raise ContractError("Run.out/RunPARTs are not from the CURRENT raw solver output")

    for key in ("gencase_receipt", "solver_receipt"):
        _assert_receipt_completed(by_key[key][0], "source." + key)

    config_path, _ = by_key["label_config"]
    config = _load_json(config_path, "label config")
    configured_physical = config.get("physical_case_id")
    if configured_physical is not None and configured_physical != physical:
        raise ContractError("label config physical_case_id differs from CURRENT case")
    geometry_source = config.get("geometry_source")
    if geometry_source is not None:
        _assert_same_path(geometry_source, by_key["generated_xml"][0], "label config geometry_source")
        if config.get("geometry_sha256") != by_key["generated_xml"][1]:
            raise ContractError("label config geometry_sha256 differs from the bound CURRENT XML")
    if config.get("frame_kind") != "fixed_solver_frame":
        raise ContractError("moving-frame label config has no bound saved transform")
    if not config.get("coordinate_frame"):
        raise ContractError("label config has no coordinate_frame")
    semantics = contract.get("semantics")
    if not isinstance(semantics, dict):
        raise ContractError("semantics object is required")
    if semantics.get("physical_fate") != "UNKNOWN" or semantics.get("dynamic_impact") != "UNKNOWN":
        raise ContractError("canary cannot grant physical fate or dynamic impact")
    if semantics.get("frame_claim") == "moving_frame_supported" and not semantics.get("transform_source"):
        raise ContractError("moving-frame claim requires a bound transform source")
    return {
        "family_id": family,
        "physical_case_id": physical,
        "current_manifest": str(current_path),
        "trajectory": str(trajectory_path),
        "trajectory_sha256": trajectory_expected,
        "config": str(config_path),
        "config_json": config,
        "frames": row.get("frames"),
        "particles": row.get("particles"),
        "actual_time_window_s": row.get("actual_time_window_s"),
        "raw_solver_output": str(solver_dir),
        "source_bindings": {key: {"path": str(path), "sha256": expected}
                            for key, path, expected in bindings},
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _output_summary(output: Path) -> dict[str, Any]:
    import h5py
    import numpy as np

    with h5py.File(output, "r") as handle:
        attrs = {str(key): handle.attrs[key] for key in handle.attrs.keys()}
        summary: dict[str, Any] = {
            "initial_fluid_mass_kg": float(attrs.get("initial_fluid_mass_kg", 0.0)),
            "frames": int(handle["time"].shape[0]),
            "identities": int(handle["particle_id"].shape[0]),
            "events": json.loads(attrs.get("config_json", "{}")).get("events", []),
        }
        for name in ("unknown_mass_kg", "numerical_loss_mass_kg", "invalid_state_mass_kg"):
            if name in handle:
                values = np.asarray(handle[name][:], dtype=float)
                summary[name + "_final"] = float(values[-1]) if len(values) else 0.0
                summary[name + "_max"] = float(np.max(values)) if len(values) else 0.0
        summary["source_final_mass_columns"] = attrs.get("source_final_columns", "")
        return summary


def run(contract_path: Path, output: Path, report: Path, *, particle_chunk: int = 65536) -> dict[str, Any]:
    contract_path = Path(contract_path).expanduser().resolve()
    contract = _load_json(contract_path, "canary contract")
    checked = validate_contract(contract, check_content=True)
    output = Path(output).expanduser().resolve()
    report = Path(report).expanduser().resolve()
    if output.exists() or report.exists():
        raise FileExistsError("forward canary refuses to overwrite an artifact")
    source = Path(checked["trajectory"])
    config = checked["config_json"]
    result = materialize(source, output, config, particle_chunk=particle_chunk)
    summary = _output_summary(output)
    result_report = {
        "schema": "ds02.stage2.family-label-report.v1",
        "status": "LABELS_MATERIALIZED_SOURCE_BOUND",
        "family_id": checked["family_id"],
        "physical_case_id": checked["physical_case_id"],
        "mechanism_id": contract["mechanism_id"],
        "task_kind": contract.get("task_kind", "finite_region_event_material"),
        "source_join": checked,
        "label_engine": {
            "schema": "ds-data-02.native-labels.v1",
            "saved_frame_chords": True,
            "hidden_continuous_events": "UNKNOWN",
            "moving_frame": "UNSUPPORTED_WITHOUT_BOUND_TRANSFORMS",
        },
        "materialization": result,
        "observed_label_summary": summary,
        "mass_gate": contract.get("mass_gate", {}),
        "physical_fate": "UNKNOWN",
        "dynamic_impact": "UNKNOWN",
        "q_n_status": "not_assessed",
        "q_e_status": "not_assessed",
        "model_invoked": False,
    }
    _atomic_json(report, result_report)
    return result_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    check = sub.add_parser("check")
    check.add_argument("--contract", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--contract", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--report", type=Path, required=True)
    run_parser.add_argument("--particle-chunk", type=int, default=65536)
    args = parser.parse_args(argv)
    if args.action == "check":
        result = validate_contract(_load_json(args.contract, "canary contract"), check_content=True)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    result = run(args.contract, args.output, args.report, particle_chunk=args.particle_chunk)
    print(json.dumps({"status": result["status"], "report": str(args.report.resolve()),
                      "output": result["materialization"]["path"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
