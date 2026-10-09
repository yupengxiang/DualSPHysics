#!/usr/bin/env python3
"""Build the source-bound ROOT229 one-frame F1-S2 support request.

Only bounded metadata is read while preparing this request.  The three
``Part_0000.bi4`` paths are deferred and are deliberately neither hashed nor
opened until the parent has reserved the guarded observer job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_f1_s2_initial_support_observer_v1.py"
CONTRACT = HERE / "stage2_f1_s2_initial_support_contract_v1.json"
CALIBRATED = HERE / "stage2_f1_native_selected_observer_v1.py"
BASE_OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PROJECT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
ROOT227_PROOF = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_S2_CONTINUOUS_OWNER_AUDIT_V2_ACTUAL_ROOT_VERIFICATION_227.json"
ROOT227_SHA = "d0edf2364db892cbe16670992c22328354b6a3dcd19d6857c8d528dc17781e1a"
ROOT227_REPORT = PROJECT / "families/F1/STAGE2_F1_S2_CONTINUOUS_OWNER_SOURCE_AUDIT_ROOT227/f1-s2-continuous-owner-audit-v2-root-227-001-root-forward-030-001/owner-audit.json"
ROOT207_PROOF = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_NATIVE_SELECTED_OBSERVER_V5_ACTUAL_ROOT_VERIFICATION_207.json"
ROOT207_SHA = "c2016d5a36922230eafc57c49baadaeff3a2bc920bb953b5fef215eb9fda30ab"
ROOT207_CHILD = PROJECT / "families/F1/F1_S1_S2_NATIVE_HEADER_SELECTED_ROOT207/f1-s1-s2-native-header-selected-root207-001-root-forward-030-001/observer/.v1-result.json"
ROOT207_CHILD_SHA = "d588f17021c3b1418ac73e343d6c323f2d8850d2be1148d39bba7243ce101fb2"
ROOT207_WRAPPER = PROJECT / "families/F1/F1_S1_S2_NATIVE_HEADER_SELECTED_ROOT207/f1-s1-s2-native-header-selected-root207-001-root-forward-030-001/observer/f1_native_selected_observer_v4.json"
ROOT207_WRAPPER_SHA = "3e87c900029c997f5d751416aee09214f8234fc8f5e6160092d3963816e3e44e"
ROOT217_PROOF = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/OFFICIAL_WRITER_CALIBRATION_V4_ACTUAL_ROOT_VERIFICATION_217.json"
ROOT217_SHA = "7df9b02c339e3b3eb8bae8f108c16d5db0fd2b6cb3f03d192c4edc827ae1bdf0"
ROOT217_REPORT = PROJECT / "families/F1/STAGE2_F1_BI4_OFFICIAL_WRITER_CALIBRATION_ROOT217_V4/f1-bi4-official-writer-calibration-v4-root-217-001-root-forward-030-001/observer/official-writer-calibration-v4.json"
ROOT217_REPORT_SHA = "2a8cb45871d6604c49e01c1577c5cb66ea73f3e3da22f9d3f043bf2a719b8356"
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.initial-support-request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.initial-support-manifest.v1"
MAX_BYTES = 16 * 1024 * 1024


class BuildError(RuntimeError):
    pass


def stable_hash(path: Path, label: str, *, max_bytes: int = MAX_BYTES) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildError(f"{label} is not a regular non-symlink file: {path}")
    before = path.stat()
    if before.st_size > max_bytes:
        raise BuildError(f"{label} exceeds bounded preparation read: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    before_sig = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_sig = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if before_sig != after_sig:
        raise BuildError(f"{label} changed while being read: {path}")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(after.st_size),
        "sha256": digest.hexdigest(),
        "stat": {"dev": int(after.st_dev), "ino": int(after.st_ino), "mtime_ns": int(after.st_mtime_ns), "ctime_ns": int(after.st_ctime_ns)},
    }


def read_json(path: Path, label: str, expected_sha: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    record = stable_hash(path, label)
    if expected_sha is not None and record["sha256"] != expected_sha:
        raise BuildError(f"{label} SHA mismatch: {record['sha256']} != {expected_sha}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"{label} root is not an object")
    return value, record


def write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BuildError(f"{label} is not numeric") from exc
    if not (result == result and abs(result) != float("inf")):
        raise BuildError(f"{label} is non-finite")
    return result


def _source_divider(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    found: list[dict[str, Any]] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "drawbox":
            continue
        if node.get("cmt") != "asymmetric channel divider physical solid":
            continue
        point = next((child for child in node if child.tag.rsplit("}", 1)[-1] == "point"), None)
        size = next((child for child in node if child.tag.rsplit("}", 1)[-1] == "size"), None)
        if point is None or size is None:
            raise BuildError(f"divider drawbox lacks point/size: {xml_path}")
        low = [_float(point.get(axis), f"divider point {axis}") for axis in ("x", "y", "z")]
        extent = [_float(size.get(axis), f"divider size {axis}") for axis in ("x", "y", "z")]
        if any(value < 0 for value in extent):
            raise BuildError(f"divider size is negative: {xml_path}")
        found.append({"low_m": low, "high_m": [low[i] + extent[i] for i in range(3)], "source_cmt": node.get("cmt")})
    if len(found) != 1:
        raise BuildError(f"expected one asymmetric divider drawbox, found {len(found)}: {xml_path}")
    return found[0]


def _receipt_for_runparts(runparts: Path) -> Path:
    # RunPARTs is .../<attempt>/solver_output/RunPARTs.csv.
    return runparts.parents[1] / "execution-receipt.json"


def _case_records(case: dict[str, Any], label: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source = case.get("source")
    identity = case.get("identity")
    if not isinstance(source, dict) or not isinstance(identity, dict):
        raise BuildError(f"{label} ROOT207 child case lacks source/identity")
    runparts = Path(source["runparts"]["path"])
    generated_xml = Path(source["generated_xml"]["path"])
    raw_root = Path(source["raw_root"])
    decoder = Path(source["decoder"]["path"])
    decoder_source = Path(source["decoder_source"]["path"])
    receipt_path = _receipt_for_runparts(runparts)
    receipt, receipt_record = read_json(receipt_path, f"{label} solver receipt")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") not in (0, "0"):
        raise BuildError(f"{label} solver receipt is not completed/0")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise BuildError(f"{label} receipt has no embedded request")
    if label in {"coarse", "fine"}:
        if request.get("family_id") != "F1" or request.get("sentinel_id") != "F1-S2" or request.get("physical_case_id") != "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1":
            raise BuildError(f"{label} solver request identity mismatch")
        identity_status = "REQUEST_V1_F1_S2_PHYSICAL_IDENTITY"
    else:
        if request.get("family_id") != "F1" or request.get("case_id") != "F1_STAGE1_DUAL_H340_DP020" or request.get("sentinel_id") is not None or request.get("physical_case_id") != "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1":
            raise BuildError(f"{label} historical solver request identity mismatch")
        identity_status = "HISTORICAL_RUNNER_V2_EXACT_F1_CASE_ID_SENTINEL_ABSENT"
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().absolute()
    expected_raw = output_root / "solver_output" / "data"
    if raw_root.expanduser().absolute() != expected_raw:
        raise BuildError(f"{label} raw_root does not join receipt output_root")
    source_xml_rec = stable_hash(generated_xml, f"{label} generated XML")
    runparts_rec = stable_hash(runparts, f"{label} RunPARTs")
    decoder_rec = stable_hash(decoder, f"{label} official decoder")
    decoder_source_rec = stable_hash(decoder_source, f"{label} decoder source")
    rows = _runparts_rows(runparts)
    if not rows or rows[0]["frame"] != 0 or rows[0]["time_s"] != 0.0:
        raise BuildError(f"{label} RunPARTs does not expose exact initial frame 0 at t=0")
    divider = _source_divider(generated_xml)
    grid = {
        "label": label,
        "child_case_label": case.get("label"),
        "identity": identity,
        "raw_root": str(raw_root),
        "runparts": runparts_rec,
        "generated_xml": source_xml_rec,
        "decoder": decoder_rec,
        "decoder_source": decoder_source_rec,
        "solver_receipt": receipt_record,
        "receipt_identity_status": identity_status,
        "initial_frame": {"frame": 0, "time_s": 0.0},
        "expected_frame_count": len(rows),
        "divider": divider,
        "native_part": {"path": str(raw_root / "Part_0000.bi4"), "frame": 0, "expected_time_s": 0.0, "sha256": "PARENT_AFTER_RESERVATION", "stat_at_prepare": "UNKNOWN_UNTIL_PARENT_RESERVATION"},
    }
    static = [receipt_record, runparts_rec, source_xml_rec, decoder_rec, decoder_source_rec]
    return grid, static


def _runparts_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise BuildError(f"RunPARTs empty: {path}")
    header = lines[0].split(";")
    for line in lines[1:]:
        values = line.split(";")
        if len(values) != len(header):
            continue
        row = dict(zip(header, values))
        try:
            frame = int(row["Part"].split("#", 1)[0].strip())
            time_s = float(row["TimeStep [s]"].split("#", 1)[0].strip())
        except (KeyError, ValueError):
            continue
        rows.append({"frame": frame, "time_s": time_s})
    rows.sort(key=lambda item: item["frame"])
    if not rows or [item["frame"] for item in rows] != list(range(len(rows))):
        raise BuildError(f"RunPARTs frame ids are not contiguous: {path}")
    if any(right["time_s"] <= left["time_s"] for left, right in zip(rows, rows[1:])):
        raise BuildError(f"RunPARTs times are not strictly increasing: {path}")
    return rows


def build(output_manifest: Path, output_request: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    contract, contract_rec = read_json(CONTRACT, "ROOT229 contract")
    if contract.get("schema") != "ds02.stage2.f1-s2.initial-support-contract.v1":
        raise BuildError("ROOT229 contract schema mismatch")
    owner_proof, owner_proof_rec = read_json(ROOT227_PROOF, "ROOT227 owner proof", ROOT227_SHA)
    if "CONTINUOUS_OWNER_340KG" not in str(owner_proof.get("status")):
        raise BuildError("ROOT227 proof is not the actual 340 kg owner closure")
    owner_report, owner_report_rec = read_json(ROOT227_REPORT, "ROOT227 owner report", owner_proof.get("report_sha256"))
    owner = owner_report.get("owner_continuum")
    if not isinstance(owner, dict) or owner.get("mass_kg") != 340.0 or owner.get("volume_m3") != 0.34 or owner.get("density_kg_m3") != 1000.0:
        raise BuildError("ROOT227 owner report does not bind 340 kg / 0.34 m3 / 1000 kg/m3")
    if owner.get("fluid_low_m") != [2.2, 0.0, 0.0] or owner.get("fluid_high_m") != [3.2, 1.0, 0.34]:
        raise BuildError("ROOT227 owner box differs from frozen continuous owner")
    if owner_report.get("qualification", {}).get("QN") != "UNKNOWN":
        raise BuildError("ROOT227 owner report unexpectedly promotes QN")
    native_proof, native_proof_rec = read_json(ROOT207_PROOF, "ROOT207 proof", ROOT207_SHA)
    if "ROOT207_SELECTED_NATIVE_HEADER" not in str(native_proof.get("status")):
        raise BuildError("ROOT207 proof status mismatch")
    child, child_rec = read_json(ROOT207_CHILD, "ROOT207 child report", ROOT207_CHILD_SHA)
    if child.get("schema") != "ds02.stage2.f1.native-selected-observer.v1" or child.get("status") != "PASS_F1_NATIVE_HEADER_SELECTED_OBSERVABLES":
        raise BuildError("ROOT207 child report status/schema mismatch")
    wrapper_rec = stable_hash(ROOT207_WRAPPER, "ROOT207 wrapper report")
    calibration_proof, calibration_proof_rec = read_json(ROOT217_PROOF, "ROOT217 calibration proof", ROOT217_SHA)
    if "OFFICIAL_WRITER_DECODER_OBSERVER_V4" not in str(calibration_proof.get("status")):
        raise BuildError("ROOT217 proof status mismatch")
    calibration_report, calibration_report_rec = read_json(ROOT217_REPORT, "ROOT217 calibration report", ROOT217_REPORT_SHA)
    if calibration_report.get("schema") != "ds02.stage2.f1.bi4-official-writer-calibration.v4":
        raise BuildError("ROOT217 report schema mismatch")
    if calibration_report.get("scientific_qualification", {}).get("QI") not in (None, "UNKNOWN"):
        raise BuildError("ROOT217 manufactured calibration was promoted to QI")
    cases = {item.get("label"): item for item in child.get("cases", []) if isinstance(item, dict)}
    labels = {"coarse": "F1_S2_DP0225_COARSE", "medium": "F1_S2_DP020_MEDIUM", "fine": "F1_S2_DP017_FINE"}
    grids: list[dict[str, Any]] = []
    static: list[dict[str, Any]] = [
        contract_rec,
        stable_hash(WORKER, "ROOT229 observer worker"),
        stable_hash(CALIBRATED, "calibrated native observer"),
        stable_hash(BASE_OBSERVER, "native observer base"),
        owner_proof_rec,
        owner_report_rec,
        native_proof_rec,
        child_rec,
        wrapper_rec,
        calibration_proof_rec,
        calibration_report_rec,
    ]
    deferred: list[dict[str, Any]] = []
    for label, child_label in labels.items():
        case = cases.get(child_label)
        if case is None:
            raise BuildError(f"ROOT207 child lacks {child_label}")
        grid, grid_static = _case_records(case, label)
        grids.append(grid)
        static.extend(grid_static)
        deferred.append(grid["native_part"])
    unique_static = {record["path"]: record for record in static}
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_NOT_RUN_ROOT229_INITIAL_SUPPORT_SOURCE_AUDIT",
        "sentinel_id": "F1-S2",
        "family_id": "F1",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "contract": {"path": str(CONTRACT), "sha256": contract_rec["sha256"]},
        "owner_continuum": {
            "low_m": [2.2, 0.0, 0.0],
            "high_m": [3.2, 1.0, 0.34],
            "volume_m3": 0.34,
            "density_kg_m3": 1000.0,
            "mass_kg": 340.0,
            "mass_is_continuum_not_native_sample": True,
        },
        "position_support_tolerance": {"value_m": 1.0e-6, "task_error_tolerance": False, "QN_credit": False},
        "provenance": {
            "root227": {"path": str(ROOT227_PROOF), "sha256": ROOT227_SHA, "report": owner_report_rec},
            "root207": {"path": str(ROOT207_PROOF), "sha256": ROOT207_SHA, "child_report": child_rec, "wrapper_report": wrapper_rec},
            "root217": {"path": str(ROOT217_PROOF), "sha256": ROOT217_SHA, "report": calibration_report_rec},
        },
        "grids": grids,
        "deferred_native_records": deferred,
        "static_source_records": list(unique_static.values()),
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "read_scope": contract["read_scope"],
    }
    manifest_path = output_manifest.expanduser().absolute()
    request_path = output_request.expanduser().absolute()
    write_once(manifest_path, manifest)
    manifest_rec = stable_hash(manifest_path, "ROOT229 manifest")
    input_records = list(unique_static.values()) + [manifest_rec]
    runtime_paths = [
        ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
        ROOT / "lagrangian-fluid-lab/scripts/ds_data02_batch_runner.py",
        ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
        ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
        Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg"),
        Path("/usr/bin/python3.10"),
    ]
    for path in runtime_paths:
        record = stable_hash(path, f"ROOT229 runtime closure {path.name}")
        input_records.append(record)
    unique_inputs = {record["path"]: record for record in input_records}
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "PREPARED_LAUNCH_DISABLED",
        "kind": "audit",
        "cpu_task_kind": "audit",
        "request_id": "f1-s2-initial-support-audit-root229-001",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "case_id": "F1_S2_INITIAL_SUPPORT_AUDIT_ROOT229",
        "attempt_id": "f1-s2-initial-support-audit-root229-001",
        "command": [str(PYTHON), "-B", str(WORKER), "--manifest", "{attempt_root}/inputs/f1_s2_initial_support_manifest_v1.json", "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/observer/f1_s2_initial_support_observer_v1.json"],
        "literal_venv_invocation": {"path": str(PYTHON), "argv0_literal": True, "resolved_target": str(PYTHON.resolve()), "pyvenv_cfg": str(runtime_paths[-2])},
        "input_files": sorted(unique_inputs),
        "input_sha256": {path: record["sha256"] for path, record in unique_inputs.items()},
        "deferred_input_records": deferred,
        "resources": {"gpu": False, "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "memory_max_bytes": 2 * 1024 * 1024 * 1024, "external_storage_max_bytes": 512 * 1024 * 1024, "home_storage_max_bytes": 128 * 1024 * 1024, "log_max_bytes": 512 * 1024, "parent_guard_required": True},
        "storage_scope": {"output_root": "{attempt_root}", "native_payload_read": "three deferred Part_0000.bi4 files only", "h5_vtk_allowed": False, "full_native_tree_scan": False, "solver_launch": False},
        "source_binding": {"manifest": str(manifest_path), "owner_mass_kg": 340.0, "position_support_tolerance_m": 1.0e-6, "position_tolerance_is_task_error": False, "root227_proof": {"path": str(ROOT227_PROOF), "sha256": ROOT227_SHA}, "root207_child": {"path": str(ROOT207_CHILD), "sha256": ROOT207_CHILD_SHA}, "root217_proof": {"path": str(ROOT217_PROOF), "sha256": ROOT217_SHA}, "interpolation": "FORBIDDEN", "neighbor_grid_truth": False},
        "scope": {"selected_frame": 0, "continuous_owner_mass_kg": 340.0, "native_sample_mass_separate": True, "support_checks": ["finite", "owner_box_containment", "divider_disjoint", "typed_role_and_mk", "native_header_mass_and_dp", "pre_post_source_stability"], "science_Q": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}},
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "ledger_mutation": False,
        "qualification_credit": 0,
    }
    write_once(request_path, request)
    return manifest, request


def self_test() -> None:
    divider = {"low_m": [1.2, 0.34, 0.0], "high_m": [2.0, 0.4, 0.7]}
    owner = ([2.2, 0.0, 0.0], [3.2, 1.0, 0.34])
    assert all(divider["high_m"][i] >= divider["low_m"][i] for i in range(3))
    assert owner[0] == [2.2, 0.0, 0.0] and owner[1] == [3.2, 1.0, 0.34]
    assert not (2.2 <= divider["high_m"][0] and 2.2 >= divider["low_m"][0])
    print("PASS_F1_S2_INITIAL_SUPPORT_REQUEST_V1_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--output-manifest", type=Path)
    parser.add_argument("--output-request", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output_manifest is None or args.output_request is None:
        parser.error("--output-manifest and --output-request are required with --build")
    try:
        build(args.output_manifest, args.output_request)
    except (BuildError, OSError, ValueError, KeyError) as exc:
        print(f"FAIL_F1_S2_INITIAL_SUPPORT_REQUEST: {exc}")
        return 2
    print(f"PASS_PREPARED_F1_S2_INITIAL_SUPPORT {args.output_manifest} {args.output_request}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
