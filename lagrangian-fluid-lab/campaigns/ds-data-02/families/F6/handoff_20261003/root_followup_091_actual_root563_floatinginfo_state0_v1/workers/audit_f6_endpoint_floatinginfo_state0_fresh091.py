#!/usr/bin/env python3
"""Verify endpoint-specific FloatingInfo angular state at native state zero.

This source-only follow-up is intentionally separate from the initial native
typed QA and from the solver request.  Root runs it only after a qualification
receipt is terminal.  It reads a bounded prefix of the semicolon-delimited
FloatingInfo CSV, the generated endpoint XML, the fresh091 canonical owner, and
the solver receipt.  The expected angular velocity is derived from the XML and
owner at execution time, so the worker cannot silently reuse a mother value.

It does not launch DualSPHysics or a postprocessor, open BI4/H5 data, or read
particle arrays.  A GenCase particle V0 observation is deliberately absent from
the acceptance rule: V0=0 does not establish that the rigid body has no angular
velocity.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "ds02.f6.endpoint-floatinginfo-state0-omega-audit-result.v1"
MAX_ROWS_DEFAULT = 8
STATE0_TIME_TOLERANCE_S = 1.0e-6
OMEGA_TOLERANCE_DEFAULT = 1.0e-5


class AuditError(RuntimeError):
    """Raised for a fail-closed metadata or bounded CSV mismatch."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise AuditError(f"{label} is missing: {path}")
    return path


def load_json(path: Path, label: str) -> dict[str, Any]:
    require_file(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AuditError(f"{label} is not a JSON object: {path}")
    return value


def finite(value: float) -> bool:
    return math.isfinite(float(value))


def normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def parse_float(raw: str, label: str) -> float:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise AuditError(f"{label} is not numeric: {raw!r}") from exc
    if not finite(value):
        raise AuditError(f"{label} is not finite: {raw!r}")
    return value


def vector_from_attributes(node: ET.Element | None, label: str) -> list[float]:
    if node is None:
        raise AuditError(f"missing XML node: {label}")
    result: list[float] = []
    for axis in "xyz":
        raw = node.get(axis)
        if raw is None:
            raise AuditError(f"missing XML {label}.{axis}")
        result.append(parse_float(raw, f"{label}.{axis}"))
    return result


def declared_omega_from_xml(path: Path) -> tuple[str, list[float]]:
    """Read only the endpoint rigid declaration from generated XML."""
    require_file(path, "generated endpoint XML")
    root = ET.parse(path).getroot()
    nodes = root.findall(".//casedef/floatings/floating/angularvelini")
    if not nodes:
        nodes = root.findall(".//floatings/floating/angularvelini")
    if len(nodes) != 1:
        raise AuditError(f"expected one XML angularvelini declaration, found {len(nodes)}: {path}")
    case_id = path.stem
    return case_id, vector_from_attributes(nodes[0], "generated.angularvelini")


def declared_omega_from_owner(path: Path) -> tuple[str, str, list[float]]:
    owner = load_json(path, "canonical owner")
    case_id = owner.get("physical_case_id")
    condition = owner.get("physical_condition_sha256")
    if not isinstance(case_id, str) or not case_id:
        raise AuditError(f"canonical owner lacks physical_case_id: {path}")
    if not isinstance(condition, str) or len(condition) != 64:
        raise AuditError(f"canonical owner lacks physical_condition_sha256: {path}")
    binding = owner.get("physical_binding")
    if not isinstance(binding, dict):
        raise AuditError(f"canonical owner lacks physical_binding: {path}")
    parameters = binding.get("parameters")
    if not isinstance(parameters, dict):
        raise AuditError(f"canonical owner lacks physical_binding.parameters: {path}")
    raw = parameters.get("initial_angular_velocity_rad_s")
    if not isinstance(raw, list) or len(raw) != 3:
        raise AuditError(f"canonical owner lacks endpoint initial angular velocity: {path}")
    omega = [parse_float(value, "owner.initial_angular_velocity_rad_s") for value in raw]
    if owner.get("physical_binding", {}).get("physical_case_id") != case_id:
        raise AuditError(f"canonical owner physical binding case mismatch: {path}")
    return case_id, condition, omega


def verify_endpoint_declaration(xml_path: Path, owner_path: Path) -> dict[str, Any]:
    xml_case, xml_omega = declared_omega_from_xml(xml_path)
    owner_case, condition, owner_omega = declared_omega_from_owner(owner_path)
    if xml_case != owner_case:
        raise AuditError(f"XML/owner case mismatch: {xml_case} != {owner_case}")
    delta = [float(left - right) for left, right in zip(xml_omega, owner_omega)]
    matches = all(abs(value) <= 1.0e-12 for value in delta)
    if not matches:
        raise AuditError(f"XML/owner angular declarations differ: {delta}")
    return {
        "physical_case_id": owner_case,
        "physical_condition_sha256": condition,
        "generated_xml": str(xml_path),
        "generated_xml_sha256": sha256(xml_path),
        "canonical_owner": str(owner_path),
        "canonical_owner_sha256": sha256(owner_path),
        "declared_angular_velocity_rad_s": owner_omega,
        "xml_owner_declaration_matches": matches,
    }


def verify_solver_receipt(path: Path) -> dict[str, Any]:
    receipt = load_json(path, "qualification solver receipt")
    status = receipt.get("status")
    returncode = receipt.get("returncode")
    if status != "completed" or returncode != 0:
        raise AuditError(f"solver receipt is not completed/0: status={status!r}, returncode={returncode!r}")
    command = receipt.get("command")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise AuditError("solver receipt command is not an argv list")
    options = [item for item in command if item.startswith("-tmax:") or item.startswith("-tout:")]
    if options != ["-tmax:12", "-tout:0.05"]:
        raise AuditError(f"solver receipt time options differ from mother: {options!r}")
    forbidden_prefixes = ("-dbc", "-motion", "-forcing", "-cpu")
    forbidden = [item for item in command if item.startswith(forbidden_prefixes)]
    if forbidden:
        raise AuditError(f"solver receipt has forbidden extra options: {forbidden!r}")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "status": status,
        "returncode": int(returncode),
        "command": command,
        "time_options": options,
    }


def field_index(headers: Sequence[str], aliases: Iterable[str]) -> int | None:
    lookup = {normalise(header): index for index, header in enumerate(headers)}
    for alias in aliases:
        index = lookup.get(normalise(alias))
        if index is not None:
            return index
    return None


def optional_field(row: Sequence[str], index: int | None, label: str) -> float | None:
    if index is None or index >= len(row):
        return None
    raw = str(row[index]).strip()
    if not raw:
        return None
    return parse_float(raw, label)


def vector_from_row(
    row: Sequence[str],
    headers: Sequence[str],
    aliases: Mapping[str, Iterable[str]],
    label: str,
) -> tuple[list[float] | None, list[bool]]:
    indices = [field_index(headers, aliases[axis]) for axis in "xyz"]
    values = [optional_field(row, index, f"{label}.{axis}") for axis, index in zip("xyz", indices)]
    presence = [value is not None for value in values]
    return ([float(value) for value in values] if all(presence) else None), presence


OMEGA_ALIASES: Mapping[str, tuple[str, ...]] = {
    "x": ("fomega.x", "fomegaxrads", "fomegax", "omega.x", "omegax", "angularvelocityx", "angvelx", "wx"),
    "y": ("fomega.y", "fomegayrads", "fomegay", "omega.y", "omegay", "angularvelocityy", "angvely", "wy"),
    "z": ("fomega.z", "fomegazrads", "fomegaz", "omega.z", "omegaz", "angularvelocityz", "angvelz", "wz"),
}
TIME_ALIASES = ("time", "times", "t", "timestamp", "time_s", "f.time")


def bounded_floatinginfo(path: Path, max_rows: int) -> dict[str, Any]:
    """Decode at most ``max_rows`` data rows; never materialize the CSV."""
    if max_rows < 1 or max_rows > 1024:
        raise AuditError(f"max_rows must be in [1,1024], got {max_rows}")
    require_file(path, "FloatingInfo CSV")
    with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
        header_line = ""
        for line in stream:
            if line.strip():
                header_line = line
                break
        if not header_line:
            raise AuditError(f"FloatingInfo CSV has no header: {path}")
        if ";" not in header_line:
            raise AuditError("FloatingInfo CSV header is not semicolon-delimited")
        headers = [str(value).strip() for value in next(csv.reader([header_line], delimiter=";"))]
        reader = csv.reader(stream, delimiter=";")
        rows: list[list[str]] = []
        for row_index, row in enumerate(reader):
            if row_index >= max_rows:
                break
            if row:
                rows.append(row)
    if not rows:
        raise AuditError(f"FloatingInfo CSV has no bounded data rows: {path}")
    time_index = field_index(headers, TIME_ALIASES)
    timed: list[tuple[int, float]] = []
    for index, row in enumerate(rows):
        value = optional_field(row, time_index, "FloatingInfo.time")
        if value is not None:
            timed.append((index, value))
    if not timed:
        raise AuditError("FloatingInfo CSV has no finite time field for state-0 selection")
    selected_index, selected_time = min(timed, key=lambda item: abs(item[1]))
    omega, presence = vector_from_row(rows[selected_index], headers, OMEGA_ALIASES, "FloatingInfo.omega")
    return {
        "path": str(path),
        "sha256": None,
        "hash_policy": "not_computed_because_only_bounded_prefix_is_read",
        "delimiter": ";",
        "header_columns": headers,
        "normalized_headers": [normalise(header) for header in headers],
        "rows_examined": len(rows),
        "max_rows": max_rows,
        "selected_row_index": selected_index,
        "selected_time_s": selected_time,
        "selected_omega_rad_s": omega,
        "omega_field_presence": presence,
        "bounded_prefix_only": True,
    }


def audit(
    csv_path: Path,
    xml_path: Path,
    owner_path: Path,
    solver_receipt_path: Path,
    *,
    max_rows: int,
    omega_tolerance: float,
) -> dict[str, Any]:
    endpoint = verify_endpoint_declaration(xml_path, owner_path)
    solver = verify_solver_receipt(solver_receipt_path)
    floating = bounded_floatinginfo(csv_path, max_rows)
    expected = endpoint["declared_angular_velocity_rad_s"]
    observed = floating["selected_omega_rad_s"]
    delta = None
    if observed is not None:
        delta = [float(left - right) for left, right in zip(observed, expected)]
    checks = {
        "solver_receipt_completed_returncode_zero": solver["status"] == "completed" and solver["returncode"] == 0,
        "solver_time_options_match_mother": solver["time_options"] == ["-tmax:12", "-tout:0.05"],
        "xml_owner_angular_declaration_matches": endpoint["xml_owner_declaration_matches"],
        "selected_row_is_state_zero": abs(float(floating["selected_time_s"])) <= STATE0_TIME_TOLERANCE_S,
        "state_zero_omega_fields_complete": observed is not None and all(floating["omega_field_presence"]),
        "state_zero_omega_matches_endpoint_declaration": delta is not None and all(abs(value) <= omega_tolerance for value in delta),
    }
    return {
        "schema": SCHEMA,
        "status": "pass" if all(checks.values()) else "fail",
        "endpoint": endpoint,
        "solver_receipt": solver,
        "floatinginfo": floating,
        "expected_angular_velocity_rad_s": expected,
        "observed_state0_angular_velocity_rad_s": observed,
        "delta_observed_minus_declared_rad_s": delta,
        "omega_tolerance_rad_s": omega_tolerance,
        "state0_time_tolerance_s": STATE0_TIME_TOLERANCE_S,
        "checks": checks,
        "claim_boundary": "FloatingInfo state-0 corroboration only; GenCase particle V0=0 is not used to infer absence of angular velocity; no Q-N or precision claim",
        "read_policy": "bounded semicolon CSV prefix plus XML/owner/receipt metadata; no BI4, H5, particle arrays, solver launch, or FloatingInfo launch",
    }


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--floating-info-csv", required=True, type=Path)
    parser.add_argument("--endpoint-xml", required=True, type=Path)
    parser.add_argument("--canonical-owner", required=True, type=Path)
    parser.add_argument("--solver-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS_DEFAULT)
    parser.add_argument("--omega-tolerance", type=float, default=OMEGA_TOLERANCE_DEFAULT)
    args = parser.parse_args(argv)
    try:
        if not finite(args.omega_tolerance) or args.omega_tolerance <= 0.0:
            raise AuditError("omega tolerance must be finite and positive")
        result = audit(
            args.floating_info_csv,
            args.endpoint_xml,
            args.canonical_owner,
            args.solver_receipt,
            max_rows=args.max_rows,
            omega_tolerance=args.omega_tolerance,
        )
    except (AuditError, OSError, ET.ParseError, json.JSONDecodeError) as exc:
        result = {
            "schema": SCHEMA,
            "status": "error",
            "error": str(exc),
            "claim_boundary": "No angular-state conclusion is emitted after a source or bounded-input error",
        }
    write_json(args.output, result)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
