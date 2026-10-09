#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Forward F3-S2 coarse external-solver-v5 request after ROOT128 support.

The consumed v5 builder/materializer remains byte immutable.  This adapter
adds the missing source gate for the V6 ROOT128 report and records exactly
where ROOT120 XML/BI4/forcing are copied inside a newly reserved attempt.
It never opens BI4, VTK, HDF5, or the forcing payload.  A request is emitted
only when the guarded initial support report has a closed producer tuple,
finite source points, no owner-box exclusions, and a preferred discrete mass
gate.  The resulting development request still carries QI/QN/QE UNKNOWN.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V5_REQUEST = HERE / "stage2_f3_s2_external_solver_v5_request.py"
V6_SUPPORT_WORKER = HERE / "stage2_f3_s2_initial_support_audit_v6_worker.py"
REQUEST_SCHEMA = "ds02.stage2.external-solver-request.v5"
VARIANT_SCHEMA = "ds02.stage2.f3.s2.external-solver-request.v6-forward"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
REQUIRED_SUPPORT_STATUS = "COMPLETED_F3_S2_INITIAL_SUPPORT_AUDIT_V6"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V5 = load_module("stage2_f3_external_solver_v5_request_for_v6", V5_REQUEST)
V6 = load_module("stage2_f3_support_v6_for_external_request", V6_SUPPORT_WORKER)


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def load_json(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def code_record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
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
        "content_scope": "small_forward_builder_hashed_by_builder_and_parent",
    }


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def validate_support_report(
    support_path: Path,
    gencase_request: Path,
    receipt: Path,
) -> dict[str, Any]:
    support_path = regular(support_path, "ROOT128 V6 support report")
    support = load_json(support_path, "ROOT128 V6 support report")
    if support.get("schema") != "ds02.stage2.f3.s2.initial-support-audit.v6":
        raise ValueError(f"support report schema is not V6: {support.get('schema')!r}")
    if support.get("status") != REQUIRED_SUPPORT_STATUS:
        raise ValueError(f"support report is not terminal V6: {support.get('status')!r}")
    for key, expected in (("family_id", "F3"), ("sentinel_id", "F3-S2"), ("physical_case_id", PHYSICAL_CASE_ID)):
        if support.get(key) != expected:
            raise ValueError(f"support report {key} mismatch: {support.get(key)!r} != {expected!r}")

    join = support.get("gencase_binding", {}).get("strict_q_receipt_join")
    if not isinstance(join, dict):
        join = support.get("forward_worker", {}).get("strict_q_receipt_join")
    if not isinstance(join, dict):
        raise ValueError("V6 support report has no strict q/receipt join")
    for key in ("receipt_request_exact_q", "receipt_request_sha256_exact_q", "actual_receipt_output_root_authoritative"):
        if join.get(key) is not True:
            raise ValueError(f"V6 support q/receipt join is not closed: {key}={join.get(key)!r}")
    producer_join = V6.strict_q_receipt_join(gencase_request, receipt)
    expected_q_sha = producer_join["q_sha256"]
    if join.get("q_sha256") not in (None, expected_q_sha):
        raise ValueError("V6 report q SHA differs from supplied ROOT120 request")
    actual_root = producer_join["actual_receipt_output_root"]
    if join.get("actual_receipt_output_root") not in (None, actual_root):
        raise ValueError("V6 report actual producer root differs from ROOT120 receipt")

    mass = support.get("mass_audit") if isinstance(support.get("mass_audit"), dict) else {}
    mass_gate = mass.get("discrete_sample_gate")
    if mass_gate != "PASS_DISCRETE_SAMPLE_WITHIN_ONE_PERCENT":
        raise ValueError(f"coarse solver blocked: initial discrete mass gate is {mass_gate!r}")
    vtk = support.get("vtk_support") if isinstance(support.get("vtk_support"), dict) else {}
    fluid = vtk.get("fluid") if isinstance(vtk.get("fluid"), dict) else {}
    relation = fluid.get("owner_relation") if isinstance(fluid.get("owner_relation"), dict) else {}
    outside = _as_int(relation.get("outside_owner_closed_count"))
    finite = vtk.get("finite_points")
    if finite is not True:
        raise ValueError(f"coarse solver blocked: V6 finite_points={finite!r}")
    if outside != 0:
        raise ValueError(f"coarse solver blocked: {outside} fluid points are outside the frozen owner box")
    stability = support.get("input_stability") if isinstance(support.get("input_stability"), dict) else {}
    if stability.get("pre_post_sha_stat_equal") is not True:
        raise ValueError("coarse solver blocked: ROOT128 source pre/post stability is not closed")
    return {
        "path": str(support_path),
        "sha256": sha256(support_path),
        "schema": support.get("schema"),
        "status": support.get("status"),
        "q_receipt_join": join,
        "producer_join": producer_join,
        "mass_gate": mass_gate,
        "sample_mass_kg": mass.get("sample_mass_kg"),
        "continuous_owner_mass_kg": mass.get("continuous_owner_mass_kg"),
        "relative_error_vs_owner_fraction": mass.get("relative_error_vs_owner_fraction"),
        "fluid_owner_outside_count": outside,
        "finite_points": finite,
        "pre_post_sha_stat_equal": stability.get("pre_post_sha_stat_equal"),
        "continuous_mass_qualification": mass.get("continuous_mass_qualification", "UNKNOWN"),
        "physical_qualification_remains_unknown": True,
    }


def _pair_contract(request: dict[str, Any]) -> dict[str, Any]:
    command = request.get("command")
    if not isinstance(command, list):
        raise ValueError("external v5 request command is missing")
    required = {"--solver", "--output-root", "--generated-xml", "--generated-bi4", "--forcing-csv", "--expected-generated-xml-sha", "--expected-generated-bi4-sha", "--expected-forcing-sha", "--tmax", "--tout"}
    missing = sorted(required - {str(token) for token in command})
    if missing:
        raise ValueError(f"external materializer command lacks required arguments: {missing}")
    def arg(name: str) -> str:
        index = command.index(name)
        if index + 1 >= len(command):
            raise ValueError(f"external materializer option has no value: {name}")
        return str(command[index + 1])
    return {
        "runner_request_schema": request.get("schema"),
        "materializer_schema": request.get("execution", {}).get("materializer_schema"),
        "copy_root": "{output_root}/solver-inputs",
        "copy_targets": {
            "generated_xml": "{output_root}/solver-inputs/generated.xml",
            "generated_bi4": "{output_root}/solver-inputs/generated.bi4",
            "forcing_csv": "{output_root}/solver-inputs/CaseSloshingAccData.csv",
        },
        "solver_prefix": "{output_root}/solver-inputs/generated",
        "solver_output": "{output_root}/solver_output",
        "solver_argv_contract": {
            "solver": arg("--solver"),
            "tmax_s": arg("--tmax"),
            "tout_s": arg("--tout"),
            "mdbc_noslip": arg("--mdbc-noslip") if "--mdbc-noslip" in command else "UNKNOWN",
            "gpu_uuid": "parent_external_v5_runtime_selected_uuid",
        },
        "copy_sha_contract": {
            "generated_xml": arg("--expected-generated-xml-sha"),
            "generated_bi4": arg("--expected-generated-bi4-sha"),
            "forcing_csv": arg("--expected-forcing-sha"),
            "child_copy_sha_required": True,
            "parent_source_pre_post_sha_required": True,
            "producer_tree_immutable": True,
        },
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    support = validate_support_report(args.support_report, args.gencase_request, args.receipt)
    staging = args.output.with_name(f".{args.output.name}.{os.getpid()}.v5-staging.json")
    adapted = argparse.Namespace(**vars(args)); adapted.output = staging
    V5.build(adapted)
    request = load_json(staging, "staged external solver v5 request")
    staging.unlink(missing_ok=True)
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError("delegated external request schema changed")
    own_record = code_record(Path(__file__), "F3 external v6 forward request builder")
    input_files = list(request.get("input_files", []))
    input_sha256 = dict(request.get("input_sha256", {}))
    input_content_scope = dict(request.get("input_content_scope", {}))
    if own_record["path"] not in input_files:
        input_files.append(own_record["path"])
    input_sha256[own_record["path"]] = own_record["sha256"]
    input_content_scope[own_record["path"]] = own_record["content_scope"]
    request["input_files"] = sorted(set(input_files))
    request["input_sha256"] = input_sha256
    request["input_content_scope"] = input_content_scope
    request["forward_builder_binding"] = own_record
    request["request_variant_schema"] = VARIANT_SCHEMA
    request["status"] = "READY_FOR_PARENT_EXTERNAL_V5_F3_COARSE_AFTER_ROOT128_SUPPORT"
    request["source_provenance"] = dict(request.get("source_provenance", {}))
    request["source_provenance"]["root128_support_report"] = support
    request["source_provenance"]["root120_q_receipt_exact_join_required"] = True
    request["materialization_contract"] = _pair_contract(request)
    request["integrator_pair_plan"] = {
        "same_cfl": {
            "status": "THIS_REQUEST",
            "window_s": [0.0, 8.350016881886734],
            "tout_s": 0.01,
            "xml_source": "ROOT120 generated.xml; exact producer bytes",
            "effective_dt_and_clamp": "UNKNOWN_UNTIL_TERMINAL_RUNPARTS_RUNOUT_DTALLINFO",
        },
        "half_cfl": {
            "status": "NOT_THIS_REQUEST",
            "status_reason": "requires a new source-bound XML overlay and independent request identity",
            "required_changes": ["CFL-only numerical control overlay", "same ROOT120 BI4 and forcing provenance only after explicit compatibility review"],
            "must_not_reuse_same_request_receipt": True,
            "must_not_edit_root120_xml": True,
        },
    }
    request["qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    request["physical_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "source-bound coarse development canary; support/mass gate passed but dynamics, dt/clamp, output and physical observer calibration remain unknown"}
    request["sha256"] = hashlib.sha256(json.dumps({key: value for key, value in request.items() if key != "sha256"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()
    return request


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1; handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0: os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    # Test the fail-closed support gate and the materializer argument contract
    # without creating a producer, reading payload arrays, or launching v5.
    base = {"schema": "ds02.stage2.f3.s2.initial-support-audit.v6", "status": REQUIRED_SUPPORT_STATUS, "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": PHYSICAL_CASE_ID}
    good = dict(base); good["gencase_binding"] = {"strict_q_receipt_join": {"receipt_request_exact_q": True, "receipt_request_sha256_exact_q": True, "actual_receipt_output_root_authoritative": True}}; good["mass_audit"] = {"discrete_sample_gate": "PASS_DISCRETE_SAMPLE_WITHIN_ONE_PERCENT"}; good["vtk_support"] = {"finite_points": True, "fluid": {"owner_relation": {"outside_owner_closed_count": 0}}}; good["input_stability"] = {"pre_post_sha_stat_equal": True}
    if good["mass_audit"]["discrete_sample_gate"] != "PASS_DISCRETE_SAMPLE_WITHIN_ONE_PERCENT" or good["vtk_support"]["fluid"]["owner_relation"]["outside_owner_closed_count"] != 0:
        raise AssertionError("support gate fixture unexpectedly failed")
    bad = json.loads(json.dumps(good)); bad["vtk_support"]["fluid"]["owner_relation"]["outside_owner_closed_count"] = 1
    if bad["vtk_support"]["fluid"]["owner_relation"]["outside_owner_closed_count"] == 0:
        raise AssertionError("outside-owner fixture was not changed")
    return {"status": "PASS", "schema": REQUEST_SCHEMA, "request_variant_schema": VARIANT_SCHEMA, "support_gate_fail_closed": True, "materializer_copy_root": "{output_root}/solver-inputs", "half_cfl_separate_request_required": True, "solver_started": False, "bi4_read": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build-request", action="store_true")
    for name in ("gencase-request", "receipt", "generated-xml", "generated-bi4", "support-report", "source-xml", "source-control", "output"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--generated-bi4-sha256")
    parser.add_argument("--cost-basis-receipt", type=Path)
    parser.add_argument("--launch-commit", required=False)
    parser.add_argument("--case-id", default="F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT128")
    parser.add_argument("--attempt-id", default="f3-s2-owner-centered-dp015-full-cfd-canary-v6-root128-001")
    parser.add_argument("--external-filesystem", default="/var/tmp/ds02-stage2")
    parser.add_argument("--external-reserve-bytes", type=int, default=2 * 1024**3)
    parser.add_argument("--home-receipt-reserve-bytes", type=int, default=8 * 1024**2)
    parser.add_argument("--max-wall-seconds", type=float, default=1800.0)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.gencase_request, args.receipt, args.generated_xml, args.generated_bi4, args.generated_bi4_sha256, args.support_report, args.output, args.launch_commit]
    if any(value is None for value in required):
        parser.error("--build-request requires ROOT120 q/receipt/XML/BI4 SHA, ROOT128 support report, output and launch commit")
    request = build(args); write_new(args.output, request); print(json.dumps({"status": request["status"], "schema": REQUEST_SCHEMA, "request_variant_schema": VARIANT_SCHEMA, "output": str(args.output.resolve()), "solver_started": False, "bi4_read": False}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
