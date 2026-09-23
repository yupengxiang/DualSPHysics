#!/usr/bin/env python3
"""Independently re-audit the closed F8 R002 design without executing it.

The original R002 static PASS omitted a Definition constant that GenCase
later rejected.  This v2 review binds the immutable R001/R002 history, parses
the exact already-materialized R002 inputs, and records the failure.  It does
not repair, rewrite, materialize, or retry either scope.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import xml.etree.ElementTree as ET
from typing import Any


LAB = Path(__file__).resolve().parents[1]
R001_ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001")
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r002")
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002"
SCHEMA = "core.cfd.f8.r002_static_design_review.v2"
OUTPUT = LAB / ROOT / "static-design-review-v2/receipt.json"

R001_AUDIT = R001_ROOT / "cpu-native-preflight-postrun-audit-v1/receipt.json"
R002_REVIEW_V1 = ROOT / "static-design-review-v1/receipt.json"
R002_POSTMORTEM_V1 = ROOT / "static-design-review-postmortem-v1/receipt.json"
R002_PREFLIGHT = ROOT / "cpu-native-preflight-v1/receipt.json"
R002_LOG = ROOT / "cpu-native-preflight-v1/gencase.stdout.log"
DEFINITION = ROOT / "input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002_Def.xml"
CONTROL = ROOT / "input/acceleration/F8_OPC_q0p500_r002_acceleration.csv"
OFFICIAL_PRECEDENT = Path(
    "vendor/official/DualSPHysics_v5.4/examples/main/15_Poiseuille/CasePoiseuille_Def.xml"
)
INDEPENDENT_REVIEW = ROOT / "static-design-review-v2/independent-review.json"

REQUIRED_CONSTANTS = (
    "gravity",
    "rhop0",
    "rhopgradient",
    "hswl",
    "gamma",
    "speedsystem",
    "coefsound",
    "speedsound",
    "coefh",
    "cflnumber",
)
EXPECTED_CONTROL_HEADER = [
    "#Time", "LinearAccX", "LinearAccY", "LinearAccZ",
    "AngularAccX", "AngularAccY", "AngularAccZ",
]


def _read_regular(relative: Path) -> bytes:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"bound path must remain relative to the lab: {relative}")
    path = LAB / relative
    cursor = LAB
    for component in relative.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            raise ValueError(f"symlink is forbidden in a review binding: {relative}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"review binding is not a regular file: {relative}")
        payload = stream.read()
        after = os.fstat(stream.fileno())
    signature_before = (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns,
    )
    signature_after = (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns,
    )
    if signature_before != signature_after or len(payload) != before.st_size:
        raise ValueError(f"review binding changed while being read: {relative}")
    return payload


def _binding(relative: Path, role: str, payload: bytes) -> dict[str, Any]:
    return {
        "path": relative.as_posix(),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "role": role,
    }


def _json(payload: bytes, relative: Path) -> dict[str, Any]:
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {relative}")
    return value


def _check_control(payload: bytes, parameters: dict[str, Any]) -> dict[str, Any]:
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8")), delimiter=";"))
    header_ok = bool(rows) and rows[0] == EXPECTED_CONTROL_HEADER
    data = rows[1:] if rows else []
    times: list[float] = []
    values_finite = True
    try:
        for row in data:
            if len(row) != 7:
                values_finite = False
                break
            numbers = [float(value) for value in row]
            if not all(math.isfinite(value) for value in numbers):
                values_finite = False
                break
            times.append(numbers[0])
    except ValueError:
        values_finite = False
    expected_rows = int(parameters["total_cycles"]) * int(parameters["points_per_period"]) + 1
    increasing = len(times) == len(data) and all(b > a for a, b in zip(times, times[1:]))
    expected_end = float(parameters["t_end"])
    endpoint_ok = bool(times) and math.isclose(times[0], 0.0, abs_tol=1e-14) and math.isclose(
        times[-1], expected_end, rel_tol=1e-13, abs_tol=1e-13
    )
    return {
        "header_matches_official_acceleration_table_shape": header_ok,
        "data_rows": len(data),
        "expected_data_rows": expected_rows,
        "all_values_finite": values_finite,
        "times_strictly_increasing": increasing,
        "time_end_s": times[-1] if times else None,
        "expected_time_end_s": expected_end,
        "time_coverage_valid": endpoint_ok,
        "valid": header_ok and len(data) == expected_rows and values_finite and increasing and endpoint_ok,
    }


def build_review() -> dict[str, Any]:
    paths = [
        (R001_AUDIT, "immutable closed R001 hard-failure audit"),
        (R002_REVIEW_V1, "historical R002 static review; retained, not trusted as sufficient"),
        (R002_POSTMORTEM_V1, "R002 static-review postmortem"),
        (R002_PREFLIGHT, "immutable failed one-shot R002 CPU preflight"),
        (R002_LOG, "actual GenCase missing-hswl parser failure"),
        (DEFINITION, "exact closed R002 Definition; read-only"),
        (CONTROL, "exact closed R002 acceleration table; read-only"),
        (OFFICIAL_PRECEDENT, "official DualSPHysics v5.4 Poiseuille Definition precedent"),
        (INDEPENDENT_REVIEW, "independent read-only static review result"),
        (Path("scripts/f8_r002_static_design_review_v2.py"), "fresh R002 static-review builder"),
        (Path("tests/test_f8_r002_static_design_review_v2.py"), "fresh R002 static-review tests"),
    ]
    content = {relative: _read_regular(relative) for relative, _ in paths}
    r001 = _json(content[R001_AUDIT], R001_AUDIT)
    prior_review = _json(content[R002_REVIEW_V1], R002_REVIEW_V1)
    postmortem = _json(content[R002_POSTMORTEM_V1], R002_POSTMORTEM_V1)
    preflight = _json(content[R002_PREFLIGHT], R002_PREFLIGHT)
    independent_review = _json(content[INDEPENDENT_REVIEW], INDEPENDENT_REVIEW)

    definition_root = ET.fromstring(content[DEFINITION])
    official_root = ET.fromstring(content[OFFICIAL_PRECEDENT])
    actual_constants = [node.tag for node in definition_root.findall("./casedef/constantsdef/*")]
    official_constants = [node.tag for node in official_root.findall("./casedef/constantsdef/*")]
    missing_constants = [name for name in REQUIRED_CONSTANTS if name not in actual_constants]
    precedent_contract_valid = all(name in official_constants for name in REQUIRED_CONSTANTS)

    error_log = content[R002_LOG].decode("utf-8", errors="replace")
    gen_case_error = "missing 'hswl'" in error_log and "Finished execution (code=1)." in error_log
    control_ref_nodes = definition_root.findall(".//acctimesfile")
    control_reference = control_ref_nodes[0].attrib.get("value") if len(control_ref_nodes) == 1 else None
    expected_reference = "acceleration/F8_OPC_q0p500_r002_acceleration.csv"
    control_audit = _check_control(content[CONTROL], prior_review.get("parameters", {}))
    control_path_valid = control_reference == expected_reference and not (LAB / CONTROL).is_symlink()

    r001_closed = (
        r001.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001"
        and r001.get("failure_closure", {}).get("same_input_retry_forbidden") is True
    )
    r002_closed = (
        preflight.get("scope_id") == SCOPE
        and preflight.get("status") == "cpu_gencase_or_control_copy_failed_hard_audit"
        and preflight.get("failure_policy", "").find("same-input retry is forbidden") >= 0
        and preflight.get("execution_controls", {}).get("cpu_gencase_invoked") is True
        and preflight.get("execution_controls", {}).get("native_decode_invoked") is False
        and preflight.get("execution_controls", {}).get("solver_invoked") is False
    )
    postmortem_confirmed = (
        postmortem.get("status") == "failed_posthoc_static_design_validation"
        and any(item.get("id") == "F8-R002-MISSING-HSWL" for item in postmortem.get("findings", []))
    )

    findings: list[dict[str, str]] = []
    if not precedent_contract_valid:
        findings.append({
            "id": "OFFICIAL_PRECEDENT_CONTRACT_INCOMPLETE",
            "severity": "review_integrity_blocker",
            "detail": "The bound official v5.4 precedent no longer contains the frozen constants compatibility set.",
        })
    if "hswl" in missing_constants or gen_case_error:
        findings.append({
            "id": "R002_GENCASE_REQUIRED_HSWL_MISSING",
            "severity": "static_design_blocker",
            "detail": "The exact R002 Definition omits hswl, and its retained GenCase log rejects that same file for missing hswl.",
        })
    if missing_constants:
        findings.append({
            "id": "R002_OFFICIAL_CONSTANTS_COMPATIBILITY_GAP",
            "severity": "compatibility_gap",
            "detail": "Fields absent from the official-template compatibility set: " + ", ".join(missing_constants),
        })
    if not control_path_valid or not control_audit["valid"]:
        findings.append({
            "id": "R002_CONTROL_INPUT_STATIC_CHECK_FAILED",
            "severity": "static_design_blocker",
            "detail": "The Definition control reference or the existing acceleration table failed its read-only structural check.",
        })
    if not (r001_closed and r002_closed and postmortem_confirmed):
        findings.append({
            "id": "CLOSED_HISTORY_NOT_CONFIRMED",
            "severity": "review_integrity_blocker",
            "detail": "The review could not confirm the immutable failure and no-retry boundaries for R001/R002.",
        })

    bindings = [_binding(relative, role, content[relative]) for relative, role in paths]
    return {
        "schema": SCHEMA,
        "record_id": "f8-oscillatory-pressure-channel-r002-static-design-review-v2",
        "scope_id": SCOPE,
        "status": "r002_static_design_review_v2_failed_scope_closed_no_retry" if findings else "r002_static_design_review_v2_passed_static_only",
        "review_scope": "read-only static audit of the exact already-materialized R002 Definition/control and retained failure evidence",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "static_constraint_gaps": findings,
        "constants_compatibility": {
            "official_precedent": str(OFFICIAL_PRECEDENT),
            "official_template_fields": REQUIRED_CONSTANTS,
            "official_precedent_contains_all_fields": precedent_contract_valid,
            "r002_definition_fields": actual_constants,
            "missing_from_r002_definition": missing_constants,
            "engine_confirmed_required_field": "hswl" if gen_case_error else None,
            "engine_log_explicitly_rejects_r002": gen_case_error,
            "other_missing_fields_are_not_claimed_as_observed_genCase_errors": True,
        },
        "definition_control_audit": {
            "definition_path": DEFINITION.as_posix(),
            "definition_sha256": hashlib.sha256(content[DEFINITION]).hexdigest(),
            "control_path": CONTROL.as_posix(),
            "control_sha256": hashlib.sha256(content[CONTROL]).hexdigest(),
            "definition_control_reference": control_reference,
            "control_reference_matches_expected_r002_path": control_path_valid,
            "acceleration_table": control_audit,
            "finite_z_wall_markers_present": (
                (definition_root.find(".//setshapemode") is not None)
                and (definition_root.findtext(".//setshapemode", default="").strip() == "dp | bound")
                and any(node.text and node.text.strip() == "top|bottom" for node in definition_root.findall(".//boxfill"))
            ),
        },
        "retained_execution_evidence": {
            "r002_preflight_status": preflight.get("status"),
            "gencase_returncode": preflight.get("gencase", {}).get("returncode"),
            "native_decode_invoked": preflight.get("execution_controls", {}).get("native_decode_invoked"),
            "solver_invoked": preflight.get("execution_controls", {}).get("solver_invoked"),
            "r002_same_input_retry_forbidden": preflight.get("failure_policy", "").find("same-input retry is forbidden") >= 0,
            "r001_same_input_retry_forbidden": r001_closed,
            "previous_postmortem_confirmed": postmortem_confirmed,
        },
        "independent_review": independent_review,
        "disposition": {
            "r001_mutated_or_retried": False,
            "r002_definition_or_control_modified": False,
            "r002_outputs_reused_or_retried": False,
            "new_review_invoked_gencase_or_decoder": False,
            "new_review_invoked_solver_gpu_worker_or_queue": False,
            "next_repair_requires": "a separately named fresh F8 revision and separate scope-specific authorization; do not edit or retry R002",
        },
        "execution_controls": {
            "definition_written": False,
            "control_written": False,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "worker_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "qualification_credit": 0,
        },
        "bindings": bindings,
    }


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_review(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    review = build_review()
    payload = (json.dumps(review, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, target)
    except FileExistsError:
        raise FileExistsError(f"refusing to overwrite immutable F8 R002 static review v2: {target}")
    finally:
        os.unlink(temporary)
    _fsync_directory(target.parent)
    return review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    review = write_review(parser.parse_args(argv).output)
    print(json.dumps({key: review[key] for key in ("schema", "status", "qualification_credit", "static_constraint_gaps")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
