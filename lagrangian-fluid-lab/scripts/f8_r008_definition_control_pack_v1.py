#!/usr/bin/env python3
"""Materialize a hash-closed, static-only F8 R008 Definition/control pack.

The pack contains fresh per-case XML and acceleration tables for the frozen
15-cell qualification matrix and 32 production manifests. It deliberately
lives outside the solver's ``input/``, ``qualification-cases/`` and
``production-cases/`` namespaces. No GenCase, native decoder, solver, GPU,
worker, queue, or qualification step is invoked or authorized here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from scripts import f8_r007_static_design_review_v1 as renderer
from scripts import f8_t1_scope_design_v1 as scope


LAB = Path(__file__).resolve().parents[1]
ROOT = scope.ROOT
PACK_ROOT = ROOT / "definition-control-pack-v1"
RECEIPT_TARGET = PACK_ROOT / "receipt.json"
DESIGN_RECEIPT = ROOT / "t1-scope-design-v1/receipt.json"
R007_ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r007")
SCHEMA = "core.cfd.f8.r008_definition_control_pack.v1"
CONTROL_SAMPLES_PER_PERIOD = 64
AMPLITUDE_M_S2 = 0.01
NU_M2_S = scope.FLUID_NU_M2_S
HALF_HEIGHT_M = scope.HALF_HEIGHT_M
RHO0_KG_M3 = scope.RHO0_KG_M3
SOUND_SPEED_M_S = scope.SOUND_SPEED_M_S
LENGTH_X_M = scope.LENGTH_X_M
LENGTH_Y_M = scope.LENGTH_Y_M
FORBIDDEN_RUNTIME_DIRS = (ROOT / "input", ROOT / "qualification-cases", ROOT / "production-cases")
RENDERER_SOURCES = (
    Path("scripts/f8_r007_static_design_review_v1.py"),
    Path("scripts/f8_r006_static_design_review_v1.py"),
    Path("scripts/f8_r005_static_design_review_v1.py"),
    Path("scripts/f8_r004_static_design_review_v1.py"),
    Path("scripts/f8_r003_static_design_review_v1.py"),
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    return str(path.relative_to(LAB)) if path.is_absolute() else str(path)


def _source_binding(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(relative), "role": role, "bytes": path.stat().st_size, "sha256": sha256(path)}


def _excluded_r007_artifacts() -> list[dict[str, Any]]:
    root = LAB / R007_ROOT
    if root.is_symlink():
        raise ValueError(f"R007 no-reuse audit refuses a symlink scope root: {root}")
    if not root.is_dir():
        raise FileNotFoundError(f"closed R007 scope is required for no-reuse audit: {root}")
    paths = list(root.rglob("*"))
    symlinks = [item for item in paths if item.is_symlink()]
    if symlinks:
        raise ValueError(f"R007 no-reuse audit refuses unexpanded symlink paths: {symlinks}")
    result = []
    for path in sorted(item for item in paths if item.is_file()):
        result.append({
            "path": str(path.relative_to(LAB)),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    if not result:
        raise ValueError("R007 no-reuse audit found no input/output artifacts to fingerprint")
    return result


def _json(path: Path) -> dict[str, Any]:
    value = json.loads((LAB / path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def require_absent_namespace(lab_root: Path = LAB, namespace: Path = PACK_ROOT) -> None:
    target = lab_root / namespace
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to reuse existing static-input pack namespace: {namespace}")
    for relative in FORBIDDEN_RUNTIME_DIRS:
        path = lab_root / relative
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"R008 runtime input namespace already exists: {relative}")


def _case_values(row: dict[str, Any]) -> dict[str, float | int]:
    q = float(row["q"])
    alpha = 2.0 + 6.0 * q
    omega = alpha * alpha * NU_M2_S / (HALF_HEIGHT_M * HALF_HEIGHT_M)
    period = 2.0 * math.pi / omega
    if not (
        math.isclose(alpha, float(row["alpha"]), rel_tol=0.0, abs_tol=1e-13)
        and math.isclose(omega, float(row["omega_rad_s"]), rel_tol=1e-13, abs_tol=1e-13)
        and math.isclose(period, float(row["period_s"]), rel_tol=1e-13, abs_tol=1e-13)
    ):
        raise ValueError(f"R008 frozen q/alpha/omega/period mismatch: {row['case_id']}")
    return {
        "q": q,
        "alpha": alpha,
        "omega": omega,
        "period": period,
        "observation_start": float(row["observation_start_s"]),
        "observation_cycles": scope.OBSERVATION_CYCLES,
        "t_end": float(row["observation_end_s"]),
        "amplitude": AMPLITUDE_M_S2,
        "half_height": HALF_HEIGHT_M,
        "length_x": LENGTH_X_M,
        "length_y": LENGTH_Y_M,
        "rho0": RHO0_KG_M3,
        "viscosity": NU_M2_S,
        "dp": float(row["dp_m"]),
        "sound_speed": SOUND_SPEED_M_S,
        "points_per_period": int(row["native_output_samples_per_period"]),
        "cflnumber": float(row["cflnumber"]),
    }


def _control_end_tick(period_s: float, end_s: float) -> int:
    control_dt = period_s / CONTROL_SAMPLES_PER_PERIOD
    end_tick = int(round(end_s / control_dt))
    if not math.isclose(end_tick * control_dt, end_s, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("R008 control table endpoint is not on the frozen T/64 control grid")
    return end_tick


def render_control(row: dict[str, Any]) -> bytes:
    values = _case_values(row)
    period, omega = float(values["period"]), float(values["omega"])
    end_tick = _control_end_tick(period, float(row["observation_end_s"]))
    dt = period / CONTROL_SAMPLES_PER_PERIOD
    lines = ["#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ"]
    for tick in range(end_tick + 1):
        time_s = tick * dt
        acceleration = AMPLITUDE_M_S2 * math.sin(omega * time_s)
        if tick == 0:
            acceleration = 0.0
        lines.append(f"{time_s:.17g};{acceleration:.17g};0;0;0;0;0")
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_definition(row: dict[str, Any], control_name: str) -> bytes:
    values = _case_values(row)
    text = renderer.definition_xml(values)
    root = ET.fromstring(text)
    cfl = root.find("./casedef/constantsdef/cflnumber")
    control_ref = root.find("./execution/special/accinputs/accinput/acctimesfile")
    parameters = {item.get("key"): item for item in root.findall("./execution/parameters/parameter")}
    if cfl is None or control_ref is None or not {"TimeMax", "TimeOut", "Boundary", "ViscoTreatment", "Visco", "XYPeriodic"}.issubset(parameters):
        raise ValueError("R008 Definition renderer lost a required constants, control, or execution parameter")
    cfl.set("value", f"{float(row['cflnumber']):.17g}")
    control_ref.set("value", control_name)
    parameters["TimeMax"].set("value", f"{float(row['observation_end_s']):.17g}")
    parameters["TimeOut"].set("value", f"{float(row['native_output_dt_s']):.17g}")
    root.insert(0, ET.Comment("Fresh R008 static input candidate; not execution authority."))
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return payload + b"\n"


def validate_case(row: dict[str, Any], definition: bytes, control: bytes, control_name: str) -> dict[str, Any]:
    values = _case_values(row)
    root = ET.fromstring(definition)
    cfl = float(root.find("./casedef/constantsdef/cflnumber").get("value"))
    dp = float(root.find("./casedef/geometry/definition").get("dp"))
    rho = float(root.find("./casedef/constantsdef/rhop0").get("value"))
    gravity = root.find("./casedef/constantsdef/gravity")
    acc = root.find("./execution/special/accinputs/accinput")
    control_ref = acc.find("./acctimesfile") if acc is not None else None
    parameters = {item.get("key"): float(item.get("value")) for item in root.findall("./execution/parameters/parameter")}
    if not (
        math.isclose(cfl, float(row["cflnumber"]), rel_tol=0.0, abs_tol=1e-15)
        and math.isclose(dp, float(row["dp_m"]), rel_tol=0.0, abs_tol=1e-14)
        and rho == RHO0_KG_M3
        and gravity is not None and [float(gravity.get(axis)) for axis in ("x", "y", "z")] == [0.0, 0.0, 0.0]
        and control_ref is not None and control_ref.get("value") == control_name
        and acc.find("./globalgravity").get("value") == "0"
        and math.isclose(parameters["TimeMax"], float(row["observation_end_s"]), rel_tol=0.0, abs_tol=1e-14)
        and math.isclose(parameters["TimeOut"], float(row["native_output_dt_s"]), rel_tol=0.0, abs_tol=1e-14)
        and parameters["Boundary"] == 2.0 and parameters["ViscoTreatment"] == 3.0
        and math.isclose(parameters["Visco"], NU_M2_S, rel_tol=0.0, abs_tol=1e-15)
        and parameters["XYPeriodic"] == 0.0
    ):
        raise ValueError(f"R008 Definition does not match the frozen case contract: {row['case_id']}")

    lines = control.decode("utf-8").splitlines()
    expected_header = "#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ"
    values_rows = [line.split(";") for line in lines[1:]]
    end_tick = _control_end_tick(float(values["period"]), float(row["observation_end_s"]))
    control_dt = float(values["period"]) / CONTROL_SAMPLES_PER_PERIOD
    if lines[0] != expected_header or len(values_rows) != end_tick + 1 or any(len(item) != 7 for item in values_rows):
        raise ValueError(f"R008 control table has a wrong header, row count, or field count: {row['case_id']}")
    max_force_error = 0.0
    for tick, fields in enumerate(values_rows):
        time_s, ax = float(fields[0]), float(fields[1])
        expected_time = tick * control_dt
        expected_ax = 0.0 if tick == 0 else AMPLITUDE_M_S2 * math.sin(float(values["omega"]) * expected_time)
        max_force_error = max(max_force_error, abs(ax - expected_ax))
        if not math.isclose(time_s, expected_time, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"R008 control time grid is not native T/64 for {row['case_id']}")
        if not math.isclose(ax, expected_ax, rel_tol=2e-14, abs_tol=1e-15) or any(float(x) != 0.0 for x in fields[2:]):
            raise ValueError(f"R008 control acceleration does not match the frozen sinusoid for {row['case_id']}")
    if not math.isclose(float(values_rows[-1][0]), float(row["observation_end_s"]), rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"R008 control table does not cover TimeMax exactly: {row['case_id']}")

    output_dt = float(row["native_output_dt_s"])
    end_index = int(round(float(row["observation_end_s"]) / output_dt))
    if not math.isclose(end_index * output_dt, float(row["observation_end_s"]), rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"R008 TimeMax is off the native output cadence: {row['case_id']}")
    return {
        "case_id": row["case_id"],
        "kind": row["kind"],
        "qualification_only": bool(row["qualification_only"]),
        "q": row["q"],
        "alpha": values["alpha"],
        "omega_rad_s": values["omega"],
        "period_s": values["period"],
        "dp_m": row["dp_m"],
        "cflnumber": row["cflnumber"],
        "native_output_samples_per_period": row["native_output_samples_per_period"],
        "native_output_dt_s": row["native_output_dt_s"],
        "observation_start_s": row["observation_start_s"],
        "observation_end_s": row["observation_end_s"],
        "expected_observation_output_count": row["expected_observation_output_count"],
        "full_native_output_rows_to_timemax": end_index + 1,
        "control_samples_per_period": CONTROL_SAMPLES_PER_PERIOD,
        "control_rows": len(values_rows),
        "control_end_tick": end_tick,
        "max_control_acceleration_absolute_error_m_s2": max_force_error,
        "control_covers_zero_to_timemax": True,
        "control_extrapolation_required": False,
    }


def _file_binding(relative: Path, payload: bytes, role: str) -> dict[str, Any]:
    return {"path": str(relative), "role": role, "bytes": len(payload), "sha256": sha256_bytes(payload)}


def build_pack() -> dict[str, Any]:
    design_receipt = _json(DESIGN_RECEIPT)
    if (
        design_receipt.get("schema") != scope.SCHEMA
        or design_receipt.get("scope_id") != scope.SCOPE_ID
        or design_receipt.get("status") != "static_scope_design_candidate_ready_for_independent_review"
        or design_receipt.get("qualification_credit") != 0
        or design_receipt.get("lineage_and_execution_boundary", {}).get("execution_authority_granted") is not False
    ):
        raise ValueError("R008 scope design is not the expected immutable zero-credit static parent")
    qualification = scope.qualification_matrix()
    production = scope.production_manifest()
    frozen = design_receipt["frozen_physics_and_control"]["production_cases_after_qualification"]["case_manifests_in_canonical_index_order"]
    if qualification != design_receipt["matrix"]["rows"] or production != frozen:
        raise ValueError("R008 code-generated matrices differ from the reviewed frozen receipt")
    if len(qualification) != 15 or len(production) != 32:
        raise ValueError("R008 input pack requires exactly 15 qualification and 32 production cases")

    cases: list[dict[str, Any]] = []
    case_ids: set[str] = set()
    for category, rows in (("qualification", qualification), ("production", production)):
        for row in rows:
            case_id = str(row["case_id"])
            if not re.fullmatch(r"[A-Za-z0-9_-]+", case_id) or case_id in case_ids:
                raise ValueError(f"R008 case ID is unsafe or duplicated: {case_id}")
            case_ids.add(case_id)
            control_name = f"F8_OPC_{case_id}_acceleration.csv"
            definition_name = f"F8_OPC_{case_id}_Def.xml"
            directory = PACK_ROOT / category / case_id
            definition_relative = directory / definition_name
            control_relative = directory / control_name
            definition = render_definition(row, control_name)
            control = render_control(row)
            proof = validate_case(row, definition, control, control_name)
            proof.update({
                "split": row.get("split"),
                "production_index": row.get("production_index"),
                "compare_to": row.get("compare_to"),
                "definition": _file_binding(definition_relative, definition, "fresh R008 per-case Definition XML"),
                "control": _file_binding(control_relative, control, "fresh R008 per-case acceleration CSV colocated with Definition"),
            })
            cases.append(proof)
    if len(case_ids) != 47:
        raise AssertionError("R008 requires 47 unique input case identities")

    sources = [
        _source_binding(DESIGN_RECEIPT, "Terra-reviewed frozen R008 scope and matrices"),
        _source_binding(Path("scripts/f8_t1_scope_design_v1.py"), "R008 manifest, physics, and observation-window implementation"),
        _source_binding(Path("tests/test_f8_t1_scope_design_v1.py"), "R008 scope design tests"),
        _source_binding(Path("scripts/f8_observation_window_parser_v2.py"), "closed native observation-window parser v2"),
        _source_binding(Path("tests/test_f8_observation_window_parser_v2.py"), "native observation-window parser v2 tests"),
        *[_source_binding(path, "R007-proven geometry renderer code; no R007 input/output reused") for path in RENDERER_SOURCES],
        _source_binding(Path(__file__).resolve(), "R008 static Definition/control pack generator"),
        _source_binding(Path("tests/test_f8_r008_definition_control_pack_v1.py"), "R008 Definition/control pack tests"),
    ]
    all_file_bindings = [
        file
        for case in cases
        for file in (case["definition"], case["control"])
    ]
    excluded_r007 = _excluded_r007_artifacts()
    excluded_hashes = {item["sha256"] for item in excluded_r007}
    reused_hashes = sorted({item["sha256"] for item in all_file_bindings} & excluded_hashes)
    if reused_hashes:
        raise ValueError(f"R008 input bytes collide with closed R007 artifacts: {reused_hashes}")
    return {
        "schema": SCHEMA,
        "record_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008-definition-control-pack-v1",
        "status": "static_definition_control_pack_rendered_in_memory_not_materialized",
        "scope_id": scope.SCOPE_ID,
        "family": "F8",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "case_counts": {
            "qualification": len(qualification),
            "production": len(production),
            "total": len(cases),
            "definition_files": len(all_file_bindings) // 2,
            "control_files": len(all_file_bindings) // 2,
        },
        "namespace": {
            "static_pack_root": str(PACK_ROOT),
            "solver_input_directory_created": False,
            "qualification_case_runtime_directory_created": False,
            "production_case_runtime_directory_created": False,
            "r007_input_or_output_reused": False,
        },
        "prior_artifact_exclusion_audit": {
            "scope": str(R007_ROOT),
            "scanned_prior_file_count": len(excluded_r007),
            "scanned_prior_files": excluded_r007,
            "r008_input_hash_collision_count": 0,
            "r008_input_hash_collisions": [],
            "renderer_source_reused_as_code_only": True,
        },
        "contracts": {
            "q_rule": "qualification uses reviewed 15-row matrix; production q_i=(i+0.5)/32, i=0..31",
            "alpha_rule": "alpha=2+6*q",
            "omega_rule_rad_s": "omega=alpha^2*nu/H^2",
            "control_rule": "ax(t)=0.01*sin(omega*t), ay=az=angular acceleration=0; samples every T/64 from t=0 through exact TimeMax",
            "control_endpoint_policy": "evaluate the sinusoid at the final timestamp; only t=0 is forced to exact zero",
            "output_rule": "TimeOut=T/64 or T/128 as predeclared per row; TimeMax is the inclusive observation-window end",
            "geometry_rule": "fresh R007 geometry renderer invocation with the R008 row dp; no R007 materialized Definition or control bytes reused",
            "physical_constants": {
                "rho0_kg_m3": RHO0_KG_M3,
                "nu_m2_s": NU_M2_S,
                "sound_speed_m_s": SOUND_SPEED_M_S,
                "gravity_m_s2": [0.0, 0.0, 0.0],
                "half_height_m": HALF_HEIGHT_M,
                "length_x_m": LENGTH_X_M,
                "length_y_m": LENGTH_Y_M,
                "acceleration_amplitude_m_s2": AMPLITUDE_M_S2,
                "control_samples_per_period": CONTROL_SAMPLES_PER_PERIOD,
            },
            "all_control_tables_cover_zero_to_timemax_without_extrapolation": True,
            "qualification_and_production_inputs_have_distinct_case_ids": True,
        },
        "cases": cases,
        "source_bindings": sources,
        "input_bindings": all_file_bindings,
        "execution_authority": {
            "static_pack_generation_authorized": True,
            "gencase_authorized": False,
            "native_decoder_authorized": False,
            "solver_authorized": False,
            "gpu_authorized": False,
            "worker_or_queue_authorized": False,
            "t1_qualification_authorized": False,
            "t2_macro_authorized": False,
            "new_explicit_native_preflight_authorization_required": True,
        },
        "execution_controls": {
            "definitions_rendered_in_memory": len(cases),
            "controls_rendered_in_memory": len(cases),
            "definitions_written": False,
            "controls_written": False,
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
    }


def write_pack(lab_root: Path | None = None) -> dict[str, Any]:
    lab_root = LAB if lab_root is None else lab_root
    require_absent_namespace(lab_root)
    pack = build_pack()
    target = lab_root / PACK_ROOT
    target.mkdir(parents=True)
    rendered = {str(path): payload for path, payload in _rendered_inputs()}
    for case in pack["cases"]:
        for binding in (case["definition"], case["control"]):
            path = lab_root / binding["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = rendered[binding["path"]]
            with path.open("xb") as stream:
                stream.write(payload)
    pack = _close_materialized_pack(pack, lab_root)
    receipt_path = lab_root / RECEIPT_TARGET
    with receipt_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(pack, indent=2, sort_keys=True) + "\n")
    return pack


def _close_materialized_pack(pack: dict[str, Any], lab_root: Path) -> dict[str, Any]:
    for binding in pack["input_bindings"]:
        path = lab_root / binding["path"]
        if (
            not path.is_file()
            or path.stat().st_size != binding["bytes"]
            or sha256(path) != binding["sha256"]
        ):
            raise ValueError(f"materialized R008 input does not match its precomputed hash: {binding['path']}")
    closed = dict(pack)
    closed["status"] = "static_definition_control_pack_materialized_no_execution_authority"
    closed["materialization"] = {
        "completed": True,
        "receipt_path": str(RECEIPT_TARGET),
        "definition_files_written": pack["case_counts"]["definition_files"],
        "control_files_written": pack["case_counts"]["control_files"],
        "all_94_input_hashes_revalidated_after_write": True,
    }
    closed_controls = dict(pack["execution_controls"])
    closed_controls["definitions_written"] = True
    closed_controls["controls_written"] = True
    closed["execution_controls"] = closed_controls
    return closed


def _rendered_inputs() -> list[tuple[Path, bytes]]:
    result: list[tuple[Path, bytes]] = []
    for category, rows in (("qualification", scope.qualification_matrix()), ("production", scope.production_manifest())):
        for row in rows:
            case_id = str(row["case_id"])
            control_name = f"F8_OPC_{case_id}_acceleration.csv"
            definition_name = f"F8_OPC_{case_id}_Def.xml"
            directory = PACK_ROOT / category / case_id
            result.append((directory / definition_name, render_definition(row, control_name)))
            result.append((directory / control_name, render_control(row)))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write all static input files once")
    args = parser.parse_args(argv)
    pack = write_pack() if args.write else build_pack()
    print(json.dumps({
        "status": pack["status"],
        "case_counts": pack["case_counts"],
        "execution_authority": pack["execution_authority"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
