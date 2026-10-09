#!/usr/bin/env python3
"""Build the launch-disabled ROOT202 F1 COM calibration manifest/request.

The builder reads only JSON proof/request/receipt/observer sidecars and small
RunPARTs/XML files.  It never opens a native Part file, H5, or VTK.  Existing
observer products are immutable inputs; a future guarded worker may consume
the generated request, but this builder does not launch it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1-com-observer-calibration-request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-com-observer-calibration-manifest.v1"
REPO = Path(__file__).resolve().parents[5]
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
CP = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints"
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_com_observer_calibration_v1.py"
CONTRACT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_com_observer_calibration_contract_v1.json"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is not a regular file: {path}")
    if path.suffix.lower() in {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}:
        raise ValueError(f"{label} would bind native/H5/VTK payload: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "sha256": sha256_file(path),
    }


def read(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def declared_record(path: Path, label: str, declared: dict[str, Any] | None = None) -> dict[str, Any]:
    result = record(path, label)
    if declared:
        for key in ("bytes", "mtime_ns", "sha256"):
            if key in declared and declared[key] != result[key]:
                raise ValueError(f"{label} {key} differs from producer declaration")
    return result


def proof_record(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = regular(path, label)
    proof = read(path, label)
    return record(path, label), proof


def path_record_from_declared(value: dict[str, Any], label: str) -> dict[str, Any]:
    if isinstance(value, str):
        return record(Path(value), label)
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise ValueError(f"{label} has no path record")
    return declared_record(Path(value["path"]), label, value)


def find_observer_request(receipt: dict[str, Any]) -> Path | None:
    """Find the source request nested in a canonical observer receipt, if any."""
    request = receipt.get("request", {})
    candidates: list[Path] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("observer_request", "template_request", "request"):
                child = value.get(key)
                if isinstance(child, dict) and isinstance(child.get("path"), str):
                    candidates.append(Path(child["path"]))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(request)
    for candidate in candidates:
        if candidate.exists() and candidate.suffix.lower() == ".json":
            return candidate
    return None


def source_small_records(report: dict[str, Any], label: str) -> dict[str, Any]:
    source = report.get("source", {})
    output: dict[str, Any] = {}
    for key in ("runparts", "generated_xml"):
        item = source.get(key)
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError(f"{label} observer lacks source.{key}")
        output[key] = declared_record(Path(item["path"]), f"{label} source {key}", item)
    output["raw_root"] = source.get("raw_root")
    if not isinstance(output["raw_root"], str):
        raise ValueError(f"{label} observer lacks raw_root")
    return output


def solver_binding(spec: dict[str, Any], label: str) -> dict[str, Any]:
    proof_path = CP / spec["solver_proof"]
    proof_record_value, proof = proof_record(proof_path, f"{label} solver proof")
    pair_key = spec.get("solver_pair")
    detail = proof
    if pair_key:
        detail = proof.get("pairs", {}).get(pair_key)
        if not isinstance(detail, dict):
            raise ValueError(f"{label} solver proof has no pair {pair_key}")
    if not str(proof.get("status", "")).startswith(("PASS", "VERIFIED", "ACTUAL")):
        raise ValueError(f"{label} solver proof is not successful")
    request_record = path_record_from_declared(detail["request"], f"{label} solver request")
    receipt_record = path_record_from_declared(detail["receipt"], f"{label} solver receipt")
    request = read(Path(request_record["path"]), f"{label} solver request")
    receipt = read(Path(receipt_record["path"]), f"{label} solver receipt")
    if receipt.get("status") not in ("completed", "COMPLETED", "completed0", "COMPLETED_DEVELOPMENT_UNKNOWN") or receipt.get("returncode") not in (0, None):
        raise ValueError(f"{label} solver receipt is not completed")
    return {
        "status": "BOUND",
        "proof": proof_record_value,
        "request": request_record,
        "receipt": receipt_record,
        "proof_pair": pair_key,
        "request_identity": {key: request.get(key) for key in ("family_id", "sentinel_id", "physical_case_id", "case_id", "attempt_id")},
        "receipt_status": receipt.get("status"),
    }


# The canonical five-observer proof is the immutable producer proof for the
# original S1/S2 selected rows.  The v4 proofs add the owner-centred S1 rungs.
CASE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "label": "F1_S1_DP010_SAME_CFL",
        "sentinel_id": "F1-S1", "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "grid": {"dp_m": 0.01, "variant": "same_cfl", "owner_mass_kg": 40.2},
        "canonical_proof": "F1_FIVE_NATIVE_OBSERVERS_ACTUAL_INDEPENDENT_VERIFICATION_001.json", "canonical_index": 1,
        "solver_proof": "F1_S1_SAVEDT_CFL_PAIR_INDEPENDENT_VERIFICATION_001.json", "solver_pair": "same_cfl",
    },
    {
        "label": "F1_S1_DP010_HALF_CFL",
        "sentinel_id": "F1-S1", "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "grid": {"dp_m": 0.01, "variant": "half_cfl", "owner_mass_kg": 40.2},
        "canonical_proof": "F1_FIVE_NATIVE_OBSERVERS_ACTUAL_INDEPENDENT_VERIFICATION_001.json", "canonical_index": 0,
        "solver_proof": "F1_S1_SAVEDT_CFL_PAIR_INDEPENDENT_VERIFICATION_001.json", "solver_pair": "half_cfl",
    },
    {
        "label": "F1_S2_DP0225_COARSE",
        "sentinel_id": "F1-S2", "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "grid": {"dp_m": 0.0225, "variant": "same_cfl", "owner_mass_kg": 340.0},
        "canonical_proof": "F1_FIVE_NATIVE_OBSERVERS_ACTUAL_INDEPENDENT_VERIFICATION_001.json", "canonical_index": 2,
        "solver_proof": "F1_COARSE_DP0225_FULL4S_INDEPENDENT_VERIFICATION_001.json",
    },
    {
        "label": "F1_S2_DP020_MEDIUM",
        "sentinel_id": "F1-S2", "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "grid": {"dp_m": 0.02, "variant": "same_cfl", "owner_mass_kg": 340.0},
        "canonical_proof": "F1_FIVE_NATIVE_OBSERVERS_ACTUAL_INDEPENDENT_VERIFICATION_001.json", "canonical_index": 4,
        "solver_proof": None,
        "solver_gap": "no independent terminal solver proof is bound to the selected medium observer; source snapshot proof is provenance-only",
    },
    {
        "label": "F1_S2_DP017_FINE",
        "sentinel_id": "F1-S2", "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "grid": {"dp_m": 0.017, "variant": "same_cfl", "owner_mass_kg": 340.0},
        "canonical_proof": "F1_FIVE_NATIVE_OBSERVERS_ACTUAL_INDEPENDENT_VERIFICATION_001.json", "canonical_index": 3,
        "solver_proof": "F1_FINE_DP017_FULL4S_INDEPENDENT_VERIFICATION_001.json",
    },
    {
        "label": "F1_S1_OWNER_DP005_SAME_CFL",
        "sentinel_id": "F1-S1", "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "grid": {"dp_m": 0.005, "variant": "same_cfl", "owner_mass_kg": 40.2},
        "observer_proof": "F1_DP005_SAME_CFL_NINE_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_054.json",
        "solver_proof": "F1_DP005_SAME_CFL_ACTUAL_EXTERNAL_V5_SOLVER_ROOT_VERIFICATION_040.json",
    },
    {
        "label": "F1_S1_OWNER_DP005_HALF_CFL",
        "sentinel_id": "F1-S1", "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "grid": {"dp_m": 0.005, "variant": "half_cfl", "owner_mass_kg": 40.2},
        "observer_proof": "F1_DP005_HALF_CFL_NINE_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_054.json",
        "solver_proof": "F1_DP005_HALF_CFL_ACTUAL_EXTERNAL_V5_SOLVER_ROOT_VERIFICATION_041.json",
    },
    {
        "label": "F1_S1_OWNER_DP0025_SAME_CFL",
        "sentinel_id": "F1-S1", "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "grid": {"dp_m": 0.0025, "variant": "same_cfl", "owner_mass_kg": 40.2},
        "observer_proof": "F1_DP0025_SAME_CFL_NINE_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_054.json",
        "solver_proof": "F1_DP0025_SAME_CFL_ACTUAL_EXTERNAL_V5_SOLVER_ROOT_VERIFICATION_041.json",
    },
    {
        "label": "F1_S1_OWNER_DP0025_HALF_CFL",
        "sentinel_id": "F1-S1", "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "grid": {"dp_m": 0.0025, "variant": "half_cfl", "owner_mass_kg": 40.2},
        "observer_proof": "F1_DP0025_HALF_CFL_NINE_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_054.json",
        "solver_proof": "F1_DP0025_HALF_CFL_ACTUAL_EXTERNAL_V5_SOLVER_ROOT_VERIFICATION_041.json",
    },
)


def make_observer_binding(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[Path]]:
    proof_name = spec.get("observer_proof") or spec["canonical_proof"]
    proof_path = CP / proof_name
    proof_record_value, proof = proof_record(proof_path, f"{spec['label']} observer proof")
    if spec.get("canonical_index") is not None:
        entry = proof["observations"][int(spec["canonical_index"])]
        report_path = Path(entry["output"])
        receipt_path = Path(entry["receipt"])
        request_kind = "embedded"
    else:
        report_path = Path(proof["report"])
        receipt_path = Path(proof["receipt"])
        request_kind = "file"
    report_path = regular(report_path, f"{spec['label']} observer report")
    receipt_path = regular(receipt_path, f"{spec['label']} observer receipt")
    report_record = record(report_path, f"{spec['label']} observer report")
    receipt_record = record(receipt_path, f"{spec['label']} observer receipt")
    report = read(report_path, f"{spec['label']} observer report")
    receipt = read(receipt_path, f"{spec['label']} observer receipt")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise ValueError(f"{spec['label']} observer receipt lacks request")
    observer_case_id = request.get("case_id")
    if not observer_case_id:
        raise ValueError(f"{spec['label']} observer request lacks case_id")
    observer_request: dict[str, Any] = {
        "kind": "embedded_in_receipt",
        "request_sha256": receipt.get("request_sha256"),
        "case_id": observer_case_id,
    }
    request_paths: list[Path] = []
    if request_kind == "file":
        request_path = Path(proof["request"])
        request_record = record(request_path, f"{spec['label']} observer request")
        observer_request = {"kind": "file", "record": request_record}
        request_paths.append(request_path)
    else:
        request_path = find_observer_request(receipt)
        if request_path is not None:
            request_paths.append(request_path)
            observer_request["template_request"] = record(request_path, f"{spec['label']} observer template request")
    source_records = source_small_records(report, spec["label"])
    case = {
        "label": spec["label"],
        "family_id": "F1",
        "sentinel_id": spec["sentinel_id"],
        "physical_case_id": spec["physical_case_id"],
        "identity": {"family_id": "F1", "sentinel_id": spec["sentinel_id"], "physical_case_id": spec["physical_case_id"]},
        "observer_case_id": observer_case_id,
        "grid": spec["grid"],
        "observer": {
            "proof": proof_record_value,
            "report": report_record,
            "receipt": receipt_record,
            "request": observer_request,
            "source_small_records": source_records,
        },
        "solver_evidence": {"status": "UNKNOWN", "reason": spec.get("solver_gap", "")},
    }
    if spec.get("solver_proof"):
        case["solver_evidence"] = solver_binding(spec, spec["label"])
    inputs = [proof_path, report_path, receipt_path, *request_paths]
    inputs.extend(Path(item["path"]) for key, item in source_records.items() if key in {"runparts", "generated_xml"})
    return case, report, inputs


def build_manifest() -> tuple[dict[str, Any], list[Path]]:
    cases: list[dict[str, Any]] = []
    inputs: list[Path] = [CONTRACT, WORKER, Path(__file__)]
    for spec in CASE_SPECS:
        case, _report, case_inputs = make_observer_binding(spec)
        cases.append(case)
        inputs.extend(case_inputs)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in inputs:
        path = path.expanduser().resolve()
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    contract_document = read(CONTRACT, "ROOT202 calibration contract")
    coordinate = contract_document.get("coordinate_contract")
    if not isinstance(coordinate, dict):
        raise ValueError("ROOT202 calibration contract has no coordinate_contract")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_ROOT202_SOURCE_BOUND_METADATA_ONLY",
        "preparation_scope": {
            "native_payload_read_by_builder": False,
            "hdf5_read": False,
            "vtk_read": False,
            "selected_observer_json_only": True,
            "qualification": dict({"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}),
        },
        "identity": {"family_id": "F1", "sentinel_ids": ["F1-S1", "F1-S2"], "physical_case_ids": ["F1_ECC_THICK_DBC_LOWER_HEAD_V1", "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1"]},
        "coordinate_contract": coordinate,
        "contract": record(CONTRACT, "ROOT202 calibration contract"),
        "mass_contract": {
            "native_header_required": True,
            "particle_sum_role": "diagnostic only",
            "continuum_mass": {"F1-S1": 40.2, "F1-S2": "UNKNOWN_CONTINUOUS_AUTHORITY; 340.0 is discrete source target"},
            "xml_mass_fallback": "FORBIDDEN",
            "rigid_body_mass": "UNKNOWN",
        },
        "time_contract": {
            "source": "observer decoded_s and RunPARTs_s values in actual sidecar",
            "query_policy": "selected actual rows only; no interpolation or frame-index pairing",
            "event_characteristic_time": "UNKNOWN",
            "cross_case_alignment": "UNKNOWN_UNEQUAL_SAVED_TIMES",
        },
        "cases": cases,
        "inputs": [record(path, "manifest input") for path in unique],
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return manifest, unique


def build_request(manifest_path: Path, input_paths: list[Path]) -> dict[str, Any]:
    input_records = [record(path, "request input") for path in input_paths]
    output_path = "{attempt_root}/calibration/f1_com_observer_calibration_v1.json"
    command = [str(PYTHON), str(WORKER), "--manifest", str(manifest_path.resolve()), "--output", output_path]
    return {
        "schema": "ds02.request.v1",
        "family_id": "F1",
        "sentinel_id": "F1-S1+F1-S2",
        "physical_case_id": "F1_COM_DIAGNOSTIC_SOURCE_BOUND_V1",
        "case_id": "F1_S1_S2_COM_OBSERVER_CALIBRATION_ROOT202",
        "attempt_id": "f1-s1-s2-com-observer-calibration-root202-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 300,
        "estimated_native_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 8 * 1024 * 1024,
        "estimated_peak_memory_bytes": 1024 * 1024 * 1024,
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": command,
        "input_files": [item["path"] for item in input_records],
        "input_hashes": {item["path"]: item["sha256"] for item in input_records},
        "manifest": record(manifest_path, "ROOT202 manifest"),
        "source_binding": {
            "schema": SCHEMA,
            "manifest": str(manifest_path.resolve()),
            "producer_request_receipt_proof_join": "strict; current path/stat/SHA and identity checked by worker",
            "time": "actual sidecar RunPARTs/decoded timestamps; no interpolation",
            "mass": "fluid native particle-sum only; native header and continuum mass remain explicit UNKNOWN gaps",
            "groups": "fluid COM/velocity/KE only; fixed/moving groups separately counted and excluded",
            "coordinates": "registered world x/y/z metres convention; producer axis-orientation metadata required and currently absent",
        },
        "output": {"path": output_path, "atomic": True, "refuse_overwrite": True},
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "hdf5_read": False,
        "native_payload_read": False,
        "qualification_stage": "ROOT202_SOURCE_BOUND_COM_DIAGNOSTIC_ONLY",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "resource_guard": {"gpu": "none", "solver_launch": "forbidden", "native_payload_read": "forbidden", "hdf5_read": "forbidden", "parent_guard": "not required for this metadata-only source sidecar run"},
    }


def write_exclusive(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--request-output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        manifest, inputs = build_manifest()
        if any(Path(item["path"]).suffix.lower() in {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"} for item in manifest["inputs"]):
            raise AssertionError("payload entered metadata manifest")
        print(json.dumps({"status": "PASS", "cases": len(manifest["cases"]), "inputs": len(inputs), "payload_reads": False}, sort_keys=True))
        return 0
    if args.manifest_output is None or args.request_output is None:
        parser.error("--manifest-output and --request-output are required unless --self-test is used")
    manifest, inputs = build_manifest()
    write_exclusive(args.manifest_output, manifest)
    request = build_request(args.manifest_output, inputs + [args.manifest_output])
    write_exclusive(args.request_output, request)
    print(json.dumps({"status": "PREPARED", "manifest": str(args.manifest_output.resolve()), "request": str(args.request_output.resolve()), "cases": len(manifest["cases"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
