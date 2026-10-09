#!/usr/bin/env python3
"""Prepare the ROOT316 parent-guarded four-sentinel support-audit request.

This builder consumes the small ROOT314 admission report and its small source
receipts only.  It records the existing Fluid/Bound VTK and generated BI4
files by stat, but never opens or hashes those payloads.  The emitted request
is therefore a concrete parent-reservation request; the parent must bind the
deferred payloads through its guarded wrapper before running the worker.

The F2-S2 18.876 kg value is deliberately carried as an
``UNVERIFIED_CROSS_SENTINEL_TARGET``.  It was defined for F2-S1 and is not a
scientific F2-S2 failure until an exact S2 owner geometry/control bridge is
proved.  Native XML sample masses remain diagnostics and are never rescaled
into an owner mass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
ADMISSION_SCHEMA = "ds02.stage2.four-sentinel-gencase-geometry-admission.v1"
SCHEMA = "ds02.stage2.four-sentinel-gencase-geometry-support-audit.v1"
MANIFEST_SCHEMA = "ds02.stage2.four-sentinel-gencase-geometry-support-manifest.v1"
CONTRACT_SCHEMA = "ds02.stage2.four-sentinel-gencase-geometry-support-contract.v1"
REQUEST_SCHEMA = "ds02.request.v1"
CASES = ("F2-S2", "F4-S2", "F5-S2", "F7-S1")
MAX_SMALL_BYTES = 16 * 1024 * 1024
WORKER_REL = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_four_sentinel_gencase_geometry_support_audit_v1.py")
CONTRACT_REL = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_four_sentinel_gencase_geometry_support_audit_contract_v1.json")


class BuildFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _regular(path: Path, label: str) -> Path:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _small_bytes(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise BuildFailure(f"{label} exceeds metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise BuildFailure(f"{label} changed during metadata read: {path}")
    return raw, {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "stat": after,
        "hash_status": "BOUND_SMALL_METADATA",
        "payload_read_by_builder": True,
    }


def _small_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, record = _small_bytes(path, label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be a JSON object: {path}")
    return value, record


def _stat_only(path: Path, label: str, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    path = _absolute(path)
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise BuildFailure(f"{label} is not a present regular non-symlink file: {path}")
    actual = _stat(path)
    expected_stat = (expected or {}).get("stat") or {}
    aliases = {
        "device": ("device", "dev", "st_dev"),
        "inode": ("inode", "ino", "st_ino"),
        "bytes": ("bytes",),
        "mtime_ns": ("mtime_ns",),
        "ctime_ns": ("ctime_ns",),
    }
    for target, keys in aliases.items():
        for key in keys:
            if key in expected_stat and actual[target] != int(expected_stat[key]):
                raise BuildFailure(f"{label} {target} changed: expected {expected_stat[key]}, got {actual[target]}")
            if key in expected_stat:
                break
    return {
        "path": str(path),
        "status": "PRESENT_STAT_ONLY",
        "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
        "stat": actual,
        "payload_read_by_builder": False,
    }


def _write_once(path: Path, value: Any) -> None:
    path = _absolute(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _record_from_report(path: str | Path, report_record: dict[str, Any], label: str) -> dict[str, Any]:
    """Rebind one report record to a current stat without reading payloads."""
    if not isinstance(report_record, dict) or not isinstance(report_record.get("path"), str):
        raise BuildFailure(f"{label} lacks a path record")
    actual_path = _absolute(Path(str(report_record["path"])))
    current = _stat_only(actual_path, label, report_record)
    return {
        "path": str(actual_path),
        "status": "PRESENT_STAT_ONLY",
        "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
        "stat": current["stat"],
        "stat_at_build": current["stat"],
        "payload_read_by_builder": False,
        "report_declared_stat": report_record.get("stat"),
        "report_declared_sha256": report_record.get("sha256"),
    }


def _known_small_record(report_record: dict[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(report_record, dict) or not isinstance(report_record.get("path"), str):
        raise BuildFailure(f"{label} lacks a path record")
    path = _absolute(Path(str(report_record["path"])))
    raw, current = _small_bytes(path, label)
    declared_sha = report_record.get("sha256")
    if isinstance(declared_sha, str) and current["sha256"] != declared_sha:
        raise BuildFailure(f"{label} SHA differs from admission report: {path}")
    declared_stat = report_record.get("stat") or {}
    if isinstance(declared_stat, dict):
        for key, value in declared_stat.items():
            if key in current["stat"] and current["stat"][key] != int(value):
                raise BuildFailure(f"{label} {key} differs from admission report: {path}")
    return current


def _correct_owner(case: dict[str, Any]) -> dict[str, Any]:
    sid = str(case["sentinel_id"])
    old = case.get("continuous_owner") if isinstance(case.get("continuous_owner"), dict) else {}
    if sid == "F2-S2":
        native = old.get("native_xml_sample_mass_kg")
        return {
            "status": "UNVERIFIED_CROSS_SENTINEL_TARGET",
            "target_mass_kg": 18.876,
            "target_source_sentinel": "F2-S1",
            "native_xml_sample_mass_kg": native,
            "native_sample_mass_scope": "F2-S2 discrete generated-XML diagnostic only",
            "mass_comparison_scope": "diagnostic_only_not_F2_S2_hard_failure",
            "mass_rescale": False,
            "required_evidence": [
                "exact F2-S2 continuous-owner geometry/volume formula",
                "exact F2-S2 source geometry/control bridge to the F2-S1 owner target",
                "parent-guarded Fluid/Bound finite/support/contact audit",
            ],
            "existing_native_vs_target_relative_pct": old.get("native_sample_vs_owner_relative_pct"),
        }
    return {
        "status": "UNKNOWN_CONTINUOUS_OWNER",
        "target_mass_kg": None,
        "target_source_sentinel": None,
        "native_xml_sample_mass_kg": old.get("native_xml_sample_mass_kg"),
        "native_sample_mass_scope": "discrete generated-XML diagnostic only",
        "mass_comparison_scope": "not_available_without_source_owner_contract",
        "mass_rescale": False,
        "required_evidence": [
            "source-bound continuous-owner geometry/volume formula",
            "parent-guarded Fluid/Bound finite/support/contact audit",
        ],
    }


def _case_from_admission(case: dict[str, Any], source_report_record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    sid = str(case.get("sentinel_id"))
    if sid not in CASES:
        raise BuildFailure(f"unexpected sentinel in admission report: {sid}")
    generated_products = (case.get("gencase") or {}).get("generated_products") or {}
    for key in ("generated_xml", "generated_bi4", "fluid_vtk", "bound_vtk"):
        if not isinstance(generated_products.get(key), dict):
            raise BuildFailure(f"{sid} admission report lacks {key}")
    source_xml = _known_small_record(case.get("source_xml"), f"{sid} source XML")
    generated_xml = _known_small_record(generated_products["generated_xml"], f"{sid} generated XML")
    if source_xml["sha256"] != generated_xml["sha256"]:
        raise BuildFailure(f"{sid} source/generated XML SHA mismatch")
    gencase_receipt = _known_small_record((case.get("gencase") or {}).get("receipt"), f"{sid} GenCase receipt")
    solver_receipt = _known_small_record((case.get("current_solver") or {}).get("receipt"), f"{sid} current solver receipt")
    gencase_receipt_value, _ = _small_json(Path(gencase_receipt["path"]), f"{sid} GenCase receipt")
    solver_receipt_value, _ = _small_json(Path(solver_receipt["path"]), f"{sid} current solver receipt")
    if gencase_receipt_value.get("status") != "completed" or int(gencase_receipt_value.get("returncode", -1)) != 0:
        raise BuildFailure(f"{sid} GenCase receipt is not completed rc=0")
    if solver_receipt_value.get("status") != "completed" or int(solver_receipt_value.get("returncode", -1)) != 0:
        raise BuildFailure(f"{sid} current solver receipt is not completed rc=0")
    deferred: dict[str, dict[str, Any]] = {}
    for key, label in (("fluid_vtk", "Fluid VTK"), ("bound_vtk", "Bound VTK"), ("generated_bi4", "generated BI4")):
        deferred[key] = _record_from_report(generated_products[key].get("path", ""), generated_products[key], f"{sid} {label}")
    owner = _correct_owner(case)
    identity = (case.get("gencase") or {}).get("identity") or {}
    case_out = {
        "sentinel_id": sid,
        "family_id": case.get("family_id"),
        "source_row_physical_case_id": case.get("source_row_physical_case_id"),
        "producer_identity": identity,
        "source_xml": source_xml,
        "generated_xml": generated_xml,
        "gencase_receipt": gencase_receipt,
        "current_solver_receipt": solver_receipt,
        "generated_bi4": deferred["generated_bi4"],
        "fluid_vtk": deferred["fluid_vtk"],
        "bound_vtk": deferred["bound_vtk"],
        "source_geometry_metadata": case.get("source_geometry_metadata"),
        "continuous_owner": owner,
        "deferred_payloads": [deferred["fluid_vtk"], deferred["bound_vtk"], deferred["generated_bi4"]],
        "source_report_case_status": {
            "source_control": (case.get("admission") or {}).get("source_control"),
            "gencase_xml": (case.get("admission") or {}).get("source_xml_and_gencase_product"),
            "initial_support": "PARENT_GUARDED_FLUID_BOUND_VTK_REQUIRED",
        },
    }
    records = {
        source_xml["path"]: source_xml,
        generated_xml["path"]: generated_xml,
        gencase_receipt["path"]: gencase_receipt,
        solver_receipt["path"]: solver_receipt,
    }
    return case_out, records


def _validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise BuildFailure(f"support contract schema mismatch: {contract.get('schema')!r}")
    if contract.get("sentinels") != list(CASES):
        raise BuildFailure("support contract case order mismatch")
    scope = contract.get("scope") if isinstance(contract.get("scope"), dict) else {}
    if scope.get("reads_generated_bi4") is not False:
        raise BuildFailure("support contract must prohibit BI4 reads")


def _runtime_records() -> dict[str, dict[str, Any]]:
    """Bind the literal venv argv0 and its resolved interpreter metadata.

    The venv's ``bin/python`` is intentionally a symlink to the system
    interpreter.  The command must retain that literal path so the parent
    runner sees the intended environment; the resolved binary and pyvenv.cfg
    are provenance records, not replacements for argv[0].
    """
    literal = _absolute(VENV)
    if not literal.exists() or not literal.is_file():
        raise BuildFailure(f"literal venv interpreter is unavailable: {literal}")
    resolved = _absolute(literal.resolve())
    if not resolved.is_file() or resolved.is_symlink():
        raise BuildFailure(f"resolved venv interpreter is not a regular file: {resolved}")
    raw, resolved_record = _small_bytes(resolved, "resolved venv interpreter")
    literal_record = {
        "path": str(literal),
        "sha256": hashlib.sha256(literal.read_bytes()).hexdigest(),
        "stat": _stat(literal),
        "hash_status": "BOUND_LITERAL_RUNTIME_METADATA",
        "payload_read_by_builder": True,
        "resolved_path": str(resolved),
        "resolved_sha256": resolved_record["sha256"],
        "resolved_stat": resolved_record["stat"],
        "symlink": literal.is_symlink(),
    }
    records = {literal_record["path"]: literal_record,
               resolved_record["path"]: {**resolved_record, "role": "resolved_venv_interpreter"}}
    pyvenv = literal.parent.parent / "pyvenv.cfg"
    if pyvenv.exists():
        _, pyvenv_record = _small_bytes(pyvenv, "venv pyvenv.cfg")
        pyvenv_record["role"] = "venv_configuration"
        records[pyvenv_record["path"]] = pyvenv_record
    return records


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    admission, admission_record = _small_json(args.admission_report, "ROOT314 admission report")
    if admission.get("schema") != ADMISSION_SCHEMA:
        raise BuildFailure(f"admission schema mismatch: {admission.get('schema')!r}")
    cases_by_id = {str(case.get("sentinel_id")): case for case in admission.get("cases", []) if isinstance(case, dict)}
    if set(cases_by_id) != set(CASES):
        raise BuildFailure("admission report must contain exactly F2-S2/F4-S2/F5-S2/F7-S1")
    contract, contract_record = _small_json(args.contract, "support contract")
    _validate_contract(contract)
    worker_raw, worker_record = _small_bytes(args.worker, "support worker")
    if not worker_raw.startswith(b"#!"):
        raise BuildFailure("support worker lacks executable shebang")
    runtime_records = _runtime_records()
    cases: list[dict[str, Any]] = []
    records: dict[str, dict[str, Any]] = {
        admission_record["path"]: admission_record,
        contract_record["path"]: contract_record,
        worker_record["path"]: worker_record,
        **runtime_records,
    }
    for sid in CASES:
        case, case_records = _case_from_admission(cases_by_id[sid], admission_record)
        cases.append(case)
        records.update(case_records)
    worker_path = _absolute(args.worker)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARDED_VTK_SUPPORT",
        "generated_by": {
            "builder": str(_absolute(Path(__file__))),
            "worker": str(worker_path),
            "payload_read": False,
            "solver_launch": False,
        },
        "admission_report": admission_record,
        "contract": contract_record,
        "cases": cases,
        "payload_policy": {
            "fluid_vtk": "PARENT_AFTER_RESERVATION_FULL_SHA_STAT_BEFORE_AND_AFTER_DECODE",
            "bound_vtk": "PARENT_AFTER_RESERVATION_FULL_SHA_STAT_BEFORE_AND_AFTER_DECODE",
            "generated_bi4": "PARENT_AFTER_RESERVATION_STAT_ONLY; NEVER_OPENED_BY_THIS_WORKER",
            "hdf5": "FORBIDDEN",
            "solver_launch": False,
            "source_replace_or_touch": "FAIL",
        },
        "scientific_scope": {
            "continuous_owner": "PER_CASE_EXPLICIT_STATUS; F2-S2 TARGET IS UNVERIFIED_CROSS_SENTINEL_TARGET",
            "native_sample_mass": "DIAGNOSTIC_ONLY",
            "mass_rescale": False,
            "neighbor_grid_truth": False,
            "contact_interpretation": "POINT_CLOUD_DIAGNOSTIC_ONLY; NO_OVERLAP/NO_PENETRATION/FLUX CREDIT",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
    }
    manifest_path = _absolute(args.manifest_output)
    _write_once(manifest_path, manifest)
    manifest_record = _small_bytes(manifest_path, "support manifest output")[1]
    records[manifest_record["path"]] = manifest_record
    deferred_records = [payload for case in cases for payload in case["deferred_payloads"]]
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": SCHEMA,
        "status": "READY_FOR_PARENT_GUARDED_VTK_SUPPORT",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "request_id": "four-sentinel-gencase-geometry-support-root316-prepared-001",
        "family_id": "DS02-MULTI",
        "sentinel_ids": list(CASES),
        "case_id": "FOUR_SENTINEL_GENCASE_GEOMETRY_SUPPORT_ROOT316",
        "attempt_id": "ROOT316_PARENT_REBIND_REQUIRED",
        "worktree_root": str(PRIMARY),
        "cwd": str(PRIMARY),
        "command": [
            str(_absolute(VENV)),
            str(worker_path),
            "--run", "--manifest", str(manifest_path),
            "--attempt-root", "{attempt_root}",
            "--output", "{attempt_root}/report/four_sentinel_gencase_geometry_support_audit_v1.json",
        ],
        "execution_allowed": True,
        "launch_disabled": False,
        "parent_wrapper_required": True,
        "parent_v8_deferred_fields_not_credit": True,
        "input_files": sorted(records),
        "input_sha256": {path: item["sha256"] for path, item in sorted(records.items()) if isinstance(item.get("sha256"), str)},
        "input_records": records,
        "manifest": manifest_record,
        "deferred_input_records": deferred_records,
        "cases": [{
            "sentinel_id": case["sentinel_id"],
            "family_id": case["family_id"],
            "physical_case_id": case["source_row_physical_case_id"],
            "generated_xml": case["generated_xml"],
            "generated_bi4": case["generated_bi4"],
            "fluid_vtk": case["fluid_vtk"],
            "bound_vtk": case["bound_vtk"],
            "gencase_receipt": case["gencase_receipt"],
            "current_solver_receipt": case["current_solver_receipt"],
            "continuous_owner": case["continuous_owner"],
            "deferred_parent_hash_required": True,
        } for case in cases],
        "resources_planning_only": {
            "cpu_threads": 1,
            "max_wall_seconds": 1800,
            "memory_max_bytes": 4 * 1024**3,
            "scratch_max_bytes": 1024 * 1024**2,
            "gpu": "none",
            "solver_launch": False,
        },
        "read_scope": {
            "builder_small_metadata_only": True,
            "worker_reads_fluid_bound_vtk_after_reservation": True,
            "worker_reads_bi4": False,
            "hdf5": False,
            "solver_launch": False,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }
    request_path = _absolute(args.request_output)
    _write_once(request_path, request)
    return manifest, request


def _self_test() -> None:
    global VENV
    with tempfile.TemporaryDirectory(prefix="four-sentinel-support-builder-") as td:
        root = Path(td)
        VENV = root / "python"
        VENV.write_bytes(b"#!/usr/bin/env python3\n")
        admission = {
            "schema": ADMISSION_SCHEMA,
            "cases": [],
        }
        for sid in CASES:
            case = {
                "sentinel_id": sid,
                "family_id": sid.split("-")[0],
                "source_row_physical_case_id": None,
                "continuous_owner": {"native_xml_sample_mass_kg": 21.114} if sid == "F2-S2" else {"native_xml_sample_mass_kg": None},
                "source_xml": {"path": str(root / f"{sid}.xml")},
                "gencase": {"generated_products": {}},
                "current_solver": {},
            }
            xml = root / f"{sid}.xml"; xml.write_text("<case/>\n", encoding="utf-8")
            xml_record = {"path": str(xml), "sha256": hashlib.sha256(xml.read_bytes()).hexdigest(), "stat": _stat(xml)}
            receipt = root / f"{sid}-gencase-receipt.json"; receipt.write_text('{"status":"completed","returncode":0}\n', encoding="utf-8")
            solver = root / f"{sid}-solver-receipt.json"; solver.write_text('{"status":"completed","returncode":0}\n', encoding="utf-8")
            def product(name: str, data: bytes) -> dict[str, Any]:
                path = root / f"{sid}-{name}"; path.write_bytes(data)
                return {"path": str(path), "stat": _stat(path), "status": "PRESENT_STAT_ONLY"}
            case["source_xml"] = xml_record
            case["gencase"] = {"receipt": {"path": str(receipt), "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(), "stat": _stat(receipt)}, "generated_products": {
                "generated_xml": xml_record,
                "generated_bi4": product(".bi4", b"tiny-bi4"),
                "fluid_vtk": product("_Fluid.vtk", b"tiny-fluid"),
                "bound_vtk": product("_Bound.vtk", b"tiny-bound"),
            }, "identity": {"producer_physical_case_id_status": "MISSING"}}
            case["current_solver"] = {"receipt": {"path": str(solver), "sha256": hashlib.sha256(solver.read_bytes()).hexdigest(), "stat": _stat(solver)}}
            admission["cases"].append(case)
        admission_path = root / "admission.json"; admission_path.write_text(json.dumps(admission), encoding="utf-8")
        worker = root / "worker.py"; worker.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        contract = root / "contract.json"; contract.write_text(json.dumps({"schema": CONTRACT_SCHEMA, "sentinels": list(CASES), "scope": {"reads_generated_bi4": False}}), encoding="utf-8")
        class Args:
            pass
        args = Args(); args.admission_report = admission_path; args.contract = contract; args.worker = worker
        args.manifest_output = root / "manifest.json"; args.request_output = root / "request.json"
        manifest, request = build(args)
        assert manifest["cases"][0]["continuous_owner"]["status"] == "UNVERIFIED_CROSS_SENTINEL_TARGET"
        assert request["parent_wrapper_required"] is True
        assert len(request["deferred_input_records"]) == 12
        tampered = json.loads(admission_path.read_text()); tampered["cases"][0]["gencase"]["generated_products"]["fluid_vtk"]["stat"]["bytes"] += 1
        admission_path.write_text(json.dumps(tampered), encoding="utf-8")
        args.manifest_output = root / "manifest-tampered.json"; args.request_output = root / "request-tampered.json"
        try:
            build(args)
        except BuildFailure:
            pass
        else:
            raise AssertionError("tampered deferred stat was accepted")
    print("PASS_FOUR_SENTINEL_GENCASE_SUPPORT_REQUEST_BUILDER_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--admission-report", type=Path)
    parser.add_argument("--contract", type=Path, default=PRIMARY / CONTRACT_REL)
    parser.add_argument("--worker", type=Path, default=PRIMARY / WORKER_REL)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--request-output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        _self_test(); return 0
    if args.admission_report is None or args.manifest_output is None or args.request_output is None:
        parser.error("--build requires --admission-report, --manifest-output and --request-output")
    try:
        manifest, request = build(args)
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOUR_SENTINEL_SUPPORT_REQUEST_BUILDER: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": request["status"], "manifest": str(args.manifest_output), "request": str(args.request_output), "cases": list(CASES), "payload_read": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
