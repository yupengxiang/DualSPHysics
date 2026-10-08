#!/usr/bin/env python3
"""Forward F5 Y-half support audit with separate GenCase/support contracts.

V4 remains the consumed payload reader.  V7 fixes the V6 interface mistake:
``--gencase-request`` is the original GenCase request, while the support
request's parent-v8 closure is carried in a separately hashed contract file.
The worker validates both contracts and the exact terminal GenCase receipt
before V4 opens Fluid/Bound VTK.  It does not treat a planned GenCase output
root as the actual receipt root; parent materialization may override that
directory, and the report records both values.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V4_PATH = HERE / "stage2_f5_s1_clipplane_initial_support_audit_v4.py"
SCHEMA = "ds02.stage2.f5-s1.clipplane-initial-support-audit.v7"
REQUEST_SCHEMA = "ds02.request.v1"
SUPPORT_CONTRACT_SCHEMA = "ds02.stage2.f5-s1.clipplane-initial-support-contract.v7"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"
CONTINUOUS_MASS_KG = 287.736
OLD_DISCRETE_SAMPLE_MASS_KG = 254.4779834119572
EXPECTED = {
    "dp010": {"dp_m": 0.010, "pointref_m": (0.015, 0.005, 0.015)},
    "dp005": {"dp_m": 0.005, "pointref_m": (0.0125, 0.0025, 0.0125)},
}


def load_v4():
    spec = importlib.util.spec_from_file_location("stage2_f5_clipplane_support_v4_for_v7", V4_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(V4_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V4 = load_v4()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
    }


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _close(a: float, b: float, tol: float = 1e-12) -> bool:
    return abs(float(a) - float(b)) <= tol


def validate_gencase_request(request: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    """Validate the original GenCase envelope, never a support envelope."""
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError("GenCase request must use ds02.request.v1")
    if request.get("family_id") != "F5" or request.get("sentinel_id") != "F5-S1":
        raise ValueError("F5-S1 GenCase identity mismatch")
    if request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("F5 physical case identity mismatch")
    if request.get("cpu_task_kind") != "gencase" or request.get("gencase_launch") is not True:
        raise ValueError("support audit is not bound to a GenCase request")
    if request.get("solver_launch") is not False or request.get("hdf5_read") is not False or request.get("bi4_read") is not False:
        raise ValueError("GenCase request has forbidden solver/native read flags")
    binding = request.get("source_binding")
    if not isinstance(binding, dict):
        raise ValueError("GenCase request has no source_binding")
    grid = binding.get("grid")
    if grid not in EXPECTED:
        raise ValueError(f"unsupported F5 Y-half grid: {grid!r}")
    expected = EXPECTED[grid]
    if not _close(binding.get("dp_m", -1.0), expected["dp_m"]):
        raise ValueError("GenCase dp does not match registered Y-half rung")
    pointref = tuple(float(value) for value in binding.get("pointref_m", ()))
    if pointref != expected["pointref_m"]:
        raise ValueError("GenCase pointref does not match registered Y-half rung")
    if not _close(binding.get("continuous_region_mass_kg", -1.0), CONTINUOUS_MASS_KG, 1e-9):
        raise ValueError("GenCase owner mass is not the frozen source-derived 287.736 kg")
    if not _close(binding.get("old_sample_mass_kg", OLD_DISCRETE_SAMPLE_MASS_KG), OLD_DISCRETE_SAMPLE_MASS_KG, 1e-12):
        raise ValueError("GenCase changed the diagnostic old discrete sample mass")
    if binding.get("continuous_box_and_clip_unchanged") is not True:
        raise ValueError("GenCase does not preserve the continuous box and official clip")
    if binding.get("controls_and_motion_unchanged") is not True:
        raise ValueError("GenCase does not preserve source controls and motion")
    if binding.get("mass_rescale") is not False:
        raise ValueError("GenCase mass rescaling is forbidden")
    planned_root = Path(str(request.get("output_root", ""))).expanduser().resolve()
    actual_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if not str(request.get("output_root", "")).strip() or not str(receipt.get("output_root", "")).strip():
        raise ValueError("GenCase request/receipt output roots are required")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None):
        raise ValueError("GenCase receipt is not completed zero-return")
    return {
        "grid": grid,
        "expected_dp_m": expected["dp_m"],
        "expected_pointref_m": list(expected["pointref_m"]),
        "continuous_region_mass_kg": CONTINUOUS_MASS_KG,
        "old_discrete_sample_mass_kg": OLD_DISCRETE_SAMPLE_MASS_KG,
        "planned_output_root": str(planned_root),
        "actual_receipt_output_root": str(actual_root),
        "planned_root_matches_receipt": planned_root == actual_root,
        "materialized_output_root_override": planned_root != actual_root,
    }


def validate_support_contract(contract: dict[str, Any], *, contract_path: Path, expected_sha: str, gencase_path: Path, receipt_path: Path, gencase_request: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    if contract.get("schema") != SUPPORT_CONTRACT_SCHEMA:
        raise ValueError("support contract schema mismatch")
    actual_contract = record(contract_path, "V7 support contract")
    if expected_sha and actual_contract["sha256"] != expected_sha:
        raise ValueError("support contract SHA mismatch")
    q_record = contract.get("gencase_request")
    receipt_record = contract.get("gencase_receipt")
    if not isinstance(q_record, dict) or not isinstance(receipt_record, dict):
        raise ValueError("support contract has no GenCase request/receipt records")
    if Path(str(q_record.get("path", ""))).expanduser().resolve() != gencase_path.resolve() or q_record.get("sha256") != sha256(gencase_path):
        raise ValueError("support contract GenCase request binding mismatch")
    if Path(str(receipt_record.get("path", ""))).expanduser().resolve() != receipt_path.resolve() or receipt_record.get("sha256") != sha256(receipt_path):
        raise ValueError("support contract receipt binding mismatch")
    binding = contract.get("source_binding")
    if not isinstance(binding, dict):
        raise ValueError("support contract has no source_binding")
    q_binding = gencase_request["source_binding"]
    for key in ("grid", "dp_m", "pointref_m", "continuous_region_mass_kg", "old_sample_mass_kg", "continuous_box_and_clip_unchanged", "controls_and_motion_unchanged", "mass_rescale"):
        if key not in binding or binding.get(key) != q_binding.get(key):
            raise ValueError(f"support/GenCase source binding mismatch: {key}")
    closure = contract.get("parent_v8_input_closure")
    if not isinstance(closure, dict) or closure.get("deferred_input_files_used") is not False or closure.get("vtk_sha_authority") != "V7 worker pre/post full SHA after parent reservation":
        raise ValueError("support contract does not close worker-owned VTK inputs correctly")
    hashes = contract.get("worker_owned_input_hashes")
    if not isinstance(hashes, dict) or hashes.get("hash_status") != "NOT_COMPUTED_BY_BUILDER_OR_PARENT_INPUT_FILES":
        raise ValueError("support contract misstates worker-owned VTK hash scope")
    return {
        "path": actual_contract["path"],
        "pre_hash": actual_contract["sha256"],
        "pre_bytes": actual_contract["bytes"],
        "pre_mtime_ns": actual_contract["mtime_ns"],
        "pre_ctime_ns": actual_contract["ctime_ns"],
        "pre_st_dev": actual_contract["st_dev"],
        "pre_st_ino": actual_contract["st_ino"],
        "pre_post_stat_checked": True,
        "gencase_request_sha256": q_record["sha256"],
        "gencase_receipt_sha256": receipt_record["sha256"],
        "deferred_input_files_used": False,
        "worker_owned_vtk_sha_authority": closure["vtk_sha_authority"],
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    gencase_path = args.gencase_request.expanduser().resolve()
    receipt_path = args.receipt.expanduser().resolve()
    contract_path = args.support_contract.expanduser().resolve()
    gencase_request = load_json(gencase_path, "F5 GenCase request")
    receipt = load_json(receipt_path, "F5 GenCase receipt")
    identity = validate_gencase_request(gencase_request, receipt)
    contract = load_json(contract_path, "F5 V7 support contract")
    contract_info = validate_support_contract(contract, contract_path=contract_path, expected_sha=args.expected_support_contract_sha or "", gencase_path=gencase_path, receipt_path=receipt_path, gencase_request=gencase_request, receipt=receipt)
    report = V4.build_report(args)
    contract_post = record(contract_path, "F5 V7 support contract")
    stat_pairs = (("bytes", "pre_bytes"), ("mtime_ns", "pre_mtime_ns"), ("ctime_ns", "pre_ctime_ns"), ("st_dev", "pre_st_dev"), ("st_ino", "pre_st_ino"))
    if contract_post["sha256"] != contract_info["pre_hash"] or any(contract_post[left] != contract_info[right] for left, right in stat_pairs):
        raise RuntimeError("support contract changed during V7 audit")
    contract_info["post_hash"] = contract_post["sha256"]
    contract_info["pre_post_equal"] = True
    generated_dp = float(report.get("generated", {}).get("dp_m", -1.0))
    if not _close(generated_dp, identity["expected_dp_m"]):
        raise ValueError("terminal generated XML dp differs from the bound GenCase rung")
    dynamic_pre = report.get("inputs", {}).get("dynamic_pre", {})
    dynamic_post = report.get("inputs", {}).get("dynamic_post", {})
    if not isinstance(dynamic_pre, dict) or not isinstance(dynamic_post, dict):
        raise ValueError("V4 report has no dynamic pre/post input records")
    for key in ("fluid_vtk", "bound_vtk"):
        pre = dynamic_pre.get(key)
        post = dynamic_post.get(key)
        if not isinstance(pre, dict) or not isinstance(post, dict):
            raise ValueError(f"V4 report has no dynamic pre/post record for {key}")
        for field in ("sha256", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if pre.get(field) != post.get(field):
                raise ValueError(f"{key} changed between V4 dynamic pre/post checks: {field}")
    report["schema"] = SCHEMA
    report["status"] = "COMPLETED_F5_YHALF_INITIAL_SUPPORT_MASS_CONTROL_AUDIT_V7"
    report["gencase_binding"] = identity
    report["support_envelope"] = contract_info
    report["candidate_contract"] = {
        "grid": identity["grid"],
        "expected_dp_m": identity["expected_dp_m"],
        "expected_pointref_m": identity["expected_pointref_m"],
        "continuous_owner_mass_kg": CONTINUOUS_MASS_KG,
        "old_discrete_sample_mass_kg": OLD_DISCRETE_SAMPLE_MASS_KG,
        "old_discrete_sample_is_diagnostic_only": True,
        "official_clip_and_box_unchanged": True,
        "controls_and_motion_unchanged": True,
        "mass_rescale": False,
    }
    report["source_closure"] = {
        "gencase_request_sha_receipt_sha_checked": True,
        "planned_vs_actual_output_root_recorded": True,
        "support_contract_sha_stat_checked": True,
        "worker_owned_vtk_dynamic_pre_post_sha_stat_equal": True,
        "worker_owned_vtk_hash_scope": "V4 dynamic_pre/dynamic_post full SHA and stat around the V3 parser, after parent reservation; no builder/local payload hash",
        "worker_owned_vtk_exact_parser_consumed_byte_hash": "NOT_COMPUTED_BY_V3_READER",
        "worker_owned_vtk_immediate_consumer_hash_claim": False,
    }
    report["qualification"] = {
        "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        "reason": "actual Y-half GenCase XML/Fluid/Bound VTK support and source-derived continuous mass audit only; solver and scientific qualification remain pending",
    }
    return report


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable V7 report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{__import__('os').getpid()}.tmp")
    if temporary.exists():
        raise FileExistsError(f"refuse to reuse V7 temporary report: {temporary}")
    try:
        fd = __import__('os').open(temporary, __import__('os').O_CREAT | __import__('os').O_EXCL | __import__('os').O_WRONLY, 0o644)
        try:
            with __import__('os').fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(payload)
                handle.flush()
                __import__('os').fsync(handle.fileno())
        finally:
            if fd >= 0:
                __import__('os').close(fd)
        __import__('os').replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    good = {
        "schema": REQUEST_SCHEMA, "family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": PHYSICAL_CASE_ID,
        "cpu_task_kind": "gencase", "gencase_launch": True, "solver_launch": False, "hdf5_read": False, "bi4_read": False,
        "output_root": "/tmp/planned", "source_binding": {
            "grid": "dp010", "dp_m": 0.01, "pointref_m": [0.015, 0.005, 0.015],
            "continuous_region_mass_kg": CONTINUOUS_MASS_KG, "old_sample_mass_kg": OLD_DISCRETE_SAMPLE_MASS_KG,
            "continuous_box_and_clip_unchanged": True, "controls_and_motion_unchanged": True, "mass_rescale": False,
        },
    }
    receipt = {"status": "completed", "returncode": 0, "output_root": "/tmp/actual"}
    identity = validate_gencase_request(good, receipt)
    assert identity["materialized_output_root_override"] is True
    bad = json.loads(json.dumps(good)); bad["source_binding"]["mass_rescale"] = True
    try:
        validate_gencase_request(bad, receipt)
    except ValueError:
        pass
    else:
        raise AssertionError("mass-rescaled GenCase contract was accepted")
    return {"status": "PASS", "schema": SCHEMA, "gencase_contract_checked": True, "planned_actual_root_override_recorded": True, "solver_started": False, "vtk_payload_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for name in ("generated-xml", "fluid-vtk", "bound-vtk", "receipt", "candidate-def", "source-def", "candidate-motion", "source-motion", "clip-evidence", "gencase-request", "support-contract", "output"):
        parser.add_argument(f"--{name}", type=Path)
    for name in ("candidate-def", "source-def", "candidate-motion", "source-motion", "clip-evidence", "gencase-request", "generated-xml", "receipt", "support-contract"):
        parser.add_argument(f"--expected-{name}-sha")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.generated_xml, args.fluid_vtk, args.bound_vtk, args.receipt, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.clip_evidence, args.gencase_request, args.support_contract, args.output]
    if any(value is None for value in required):
        parser.error("all terminal/static paths, --support-contract and --output are required")
    report = build_report(args)
    write_new(args.output, report)
    print(json.dumps({"status": report["status"], "grid": report["gencase_binding"]["grid"], "support_gate": report["support"]["gate"], "mass_gate": report["mass_audit"]["gate"], "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
