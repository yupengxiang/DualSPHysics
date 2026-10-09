#!/usr/bin/env python3
"""Guarded single-product F3-S2 initial support/Idp audit (forward v3).

This worker is a generic forward wrapper around the already reviewed ROOT086
binary-VTK parser.  It binds one completed GenCase request/receipt (ROOT120
in the first use), generated XML, source XML/control and worker-owned Fluid /
Bound VTK files.  The parent guard reserves the attempt; only then does this
worker first hash/stat and decode the VTK payloads.  No GenCase, solver, BI4 or
HDF5 operation is performed.  Particle sample mass is compared with the
14.58-kg owner contract as an initial diagnostic; it is not a physical or
numerical qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
ROOT086_LOCAL = Path(__file__).resolve().parents[4] / "scripts/ds_data02_stage2_f3_s2_root086_vtk_support_qa_v2.py"
ROOT086_PATH = ROOT086_LOCAL if ROOT086_LOCAL.is_file() else PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_f3_s2_root086_vtk_support_qa_v2.py"
SCHEMA = "ds02.stage2.f3.s2.initial-support-audit.v3"
REQUEST_SCHEMA = "ds02.request.v1"
CONTRACT_SCHEMA = "ds02.stage2.f3.s2.initial-support-contract.v3"
OWNER_LOW = [-0.45, -0.09, 0.0]
OWNER_SIZE = [0.9, 0.18, 0.09]
OWNER_HIGH = [OWNER_LOW[i] + OWNER_SIZE[i] for i in range(3)]
OWNER_MASS_KG = 14.58
SOURCE_SAMPLE_MASS_KG = 14.58
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"


def load_root086():
    spec = importlib.util.spec_from_file_location("stage2_f3_root086_parser_for_v3", ROOT086_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(ROOT086_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ROOT086 = load_root086()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str, *, scope: str = "small_input_hashed_by_worker") -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": sha256(path), "content_scope": scope}


def first_payload(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    path = regular(path, label)
    before = path.stat()
    with path.open("rb") as handle:
        data = handle.read()
    after = path.stat()
    fields = ("st_size", "st_mtime_ns", "st_ctime_ns", "st_dev", "st_ino")
    if tuple(getattr(before, field) for field in fields) != tuple(getattr(after, field) for field in fields):
        raise RuntimeError(f"{label} changed during first worker read")
    return data, {"path": str(path), "label": label, "bytes": int(len(data)), "mtime_ns": int(after.st_mtime_ns), "ctime_ns": int(after.st_ctime_ns), "st_dev": int(after.st_dev), "st_ino": int(after.st_ino), "sha256": hashlib.sha256(data).hexdigest(), "content_scope": "worker_first_payload_hash_after_parent_reservation"}


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def validate_binding(q: dict[str, Any], receipt: dict[str, Any], q_path: Path, receipt_path: Path) -> dict[str, Any]:
    scope = q.get("scope") if isinstance(q.get("scope"), dict) else {}
    family_id = q.get("family_id") or scope.get("family_id")
    sentinel_id = q.get("sentinel_id") or scope.get("sentinel_id")
    physical_case_id = q.get("physical_case_id") or scope.get("physical_case_id")
    if q.get("schema") != REQUEST_SCHEMA or family_id != "F3" or sentinel_id != "F3-S2":
        raise ValueError("F3-S2 GenCase request identity mismatch")
    if physical_case_id != PHYSICAL_CASE_ID:
        raise ValueError("F3 physical case identity mismatch")
    if q.get("cpu_task_kind") != "gencase" or q.get("solver_launch") is not False:
        raise ValueError("support worker is not bound to a GenCase-only request")
    if q.get("gencase_launch", True) is not True or q.get("hdf5_read", False) is not False or q.get("bi4_read", False) is not False:
        raise ValueError("GenCase request allows forbidden native/HDF5 reads")
    binding = q.get("source_binding") if isinstance(q.get("source_binding"), dict) else scope
    if not isinstance(binding, dict) or (binding.get("grid", "dp015") not in {"dp015", "coarse_dp015"} and binding.get("mode") != "new_gencase"):
        raise ValueError("F3 support v3 requires the dp015 source-bound grid")
    receipt_status = str(receipt.get("status", "")).lower()
    if receipt_status not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None):
        raise ValueError("GenCase receipt is not completed zero-return")
    q_root_value = q.get("output_root")
    q_root = Path(str(q_root_value)).expanduser().resolve() if q_root_value else None
    receipt_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if not str(receipt.get("output_root", "")).strip():
        raise ValueError("receipt output root is required")
    return {"q_path": str(q_path.resolve()), "receipt_path": str(receipt_path.resolve()), "planned_output_root": str(q_root) if q_root else "UNKNOWN_NOT_DECLARED_BY_SOURCE_REQUEST", "actual_receipt_output_root": str(receipt_root), "planned_root_matches_receipt": q_root == receipt_root if q_root else "UNKNOWN_SOURCE_REQUEST_NO_OUTPUT_ROOT", "dp_m": float(binding.get("dp_m", 0.0)), "pointref_m": list(binding.get("pointref_m", binding.get("phase", {}).get("pointref_m", []))), "gencase_case_id": q.get("case_id"), "gencase_attempt_id": q.get("attempt_id")}


def parse_blocks(path: Path) -> tuple[dict[str, Any], list[dict[str, int]]]:
    root = ET.parse(path).getroot()
    blocks: list[dict[str, int]] = []
    particles = next((node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "particles"), None)
    if particles is None:
        raise ValueError("generated XML has no particles block")
    for node in particles:
        if node.tag.rsplit("}", 1)[-1] == "fluid" and all(node.get(key) is not None for key in ("mkfluid", "mk", "begin", "count")):
            blocks.append({key: int(node.get(key)) for key in ("mkfluid", "mk", "begin", "count")})
    if not blocks:
        raise ValueError("generated XML has no typed fluid blocks")
    definition = next((node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "definition"), None)
    mass_node = next((node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "massfluid"), None)
    if definition is None or mass_node is None:
        raise ValueError("generated XML lacks definition or massfluid")
    count = sum(item["count"] for item in blocks)
    fixed = int(particles.get("nb", "0"))
    total = int(particles.get("np", str(fixed + count)))
    generated = {"dp_m": float(definition.get("dp")), "pointref_m": [float(next(node for node in definition if node.tag.rsplit("}", 1)[-1] == "pointref").get(axis)) for axis in "xyz"], "fluid_blocks": blocks, "fluid_count": count, "fixed_or_bound_count": fixed, "total_particles": total, "massfluid_kg": float(mass_node.get("value")), "sample_mass_kg": count * float(mass_node.get("value"))}
    return generated, blocks


def receipt_control_binding(receipt: dict[str, Any], control: Path) -> dict[str, Any]:
    digest = sha256(control)
    matches: list[str] = []
    for container in (receipt.get("request", {}), receipt.get("input_hashes_at_launch", {}), receipt.get("input_hashes_after_run", {})):
        if not isinstance(container, dict):
            continue
        mapping = container.get("input_sha256") if isinstance(container.get("input_sha256"), dict) else container
        if not isinstance(mapping, dict):
            continue
        for path, value in mapping.items():
            if isinstance(path, str) and Path(path).name == control.name and value == digest:
                matches.append(str(Path(path).expanduser().resolve()))
    return {"sha256": digest, "matching_receipt_paths": sorted(set(matches)), "status": "PASS" if matches else "UNKNOWN_RECEIPT_CONTROL_PATH_NOT_FOUND"}


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    q_path = args.gencase_request.expanduser().resolve(); receipt_path = args.receipt.expanduser().resolve()
    q = load_json(q_path, "F3 GenCase request"); receipt = load_json(receipt_path, "F3 GenCase receipt")
    identity = validate_binding(q, receipt, q_path, receipt_path)
    contract_path = args.support_contract.expanduser().resolve()
    contract = load_json(contract_path, "F3 v3 support contract")
    if contract.get("schema") != "ds02.stage2.f3.s2.initial-support-contract.v3":
        raise ValueError("F3 support contract schema mismatch")
    if args.expected_support_contract_sha and sha256(contract_path) != args.expected_support_contract_sha:
        raise ValueError("F3 support contract SHA mismatch")
    for key, path in (("gencase_request", q_path), ("gencase_receipt", receipt_path)):
        bound = contract.get(key)
        if not isinstance(bound, dict) or Path(str(bound.get("path", ""))).expanduser().resolve() != path or bound.get("sha256") != sha256(path):
            raise ValueError(f"F3 support contract {key} binding mismatch")
    generated_xml = regular(args.generated_xml, "F3 generated XML")
    fluid_vtk = regular(args.fluid_vtk, "F3 Fluid VTK")
    bound_vtk = regular(args.bound_vtk, "F3 Bound VTK")
    receipt_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    for label, path in (("generated XML", generated_xml), ("Fluid VTK", fluid_vtk), ("Bound VTK", bound_vtk)):
        if path.parent != receipt_root:
            raise ValueError(f"{label} is outside the terminal receipt output_root")
    # The support contract is the source-bound identity record.  Recheck the
    # small generated XML/source/control records before opening any dynamic
    # VTK payload; a matching q/receipt alone does not prove that the worker
    # is looking at the intended generated product or control file.
    for key, path in (("generated_xml", generated_xml), ("source_xml", args.source_xml), ("source_control", args.source_control)):
        bound = contract.get(key)
        if not isinstance(bound, dict) or Path(str(bound.get("path", ""))).expanduser().resolve() != path.resolve() or bound.get("sha256") != sha256(path):
            raise ValueError(f"F3 support contract {key} binding mismatch")
    static_paths = {"gencase_request": q_path, "receipt": receipt_path, "source_xml": args.source_xml, "source_control": args.source_control, "worker": Path(__file__).resolve(), "root086_parser": ROOT086_PATH, "support_contract": contract_path}
    static_pre = {key: record(path, f"F3 {key}") for key, path in static_paths.items()}
    dynamic_paths = {"generated_xml": generated_xml, "fluid_vtk": fluid_vtk, "bound_vtk": bound_vtk}
    payload_data: dict[str, bytes] = {}; dynamic_pre: dict[str, dict[str, Any]] = {}
    for key, path in dynamic_paths.items():
        payload_data[key], dynamic_pre[key] = first_payload(path, f"F3 {key}")
    for key, expected in (("generated_xml", args.expected_generated_xml_sha),):
        if expected and dynamic_pre[key]["sha256"] != expected:
            raise ValueError(f"{key} SHA mismatch after parent reservation")
    generated, blocks = parse_blocks(generated_xml)
    if generated["dp_m"] <= 0 or generated["fluid_count"] <= 0 or generated["massfluid_kg"] <= 0:
        raise ValueError("generated XML has invalid initial fluid metadata")
    points, fluid_meta = ROOT086.read_fluid_vtk(fluid_vtk, generated["fluid_count"], blocks[0]["begin"], generated["fluid_count"])
    bound_points, bound_meta = ROOT086.read_vtk_points(bound_vtk)
    dynamic_post = {key: record(path, f"F3 {key} post-decode", scope="worker_post_decode_full_sha_stat") for key, path in dynamic_paths.items()}
    for key in dynamic_paths:
        if dynamic_pre[key]["sha256"] != dynamic_post[key]["sha256"] or any(dynamic_pre[key].get(field) != dynamic_post[key].get(field) for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")):
            raise RuntimeError(f"dynamic F3 input changed during audit: {key}")
    owner_low = OWNER_LOW; owner_high = OWNER_HIGH; tol = max(1e-8, generated["dp_m"] * 1e-5)
    inside = ((points[:, 0] >= owner_low[0]-tol) & (points[:, 0] <= owner_high[0]+tol) & (points[:, 1] >= owner_low[1]-tol) & (points[:, 1] <= owner_high[1]+tol) & (points[:, 2] >= owner_low[2]-tol) & (points[:, 2] <= owner_high[2]+tol))
    relative = generated["sample_mass_kg"] / OWNER_MASS_KG - 1.0
    mass_gate = "PASS_DISCRETE_SAMPLE_WITHIN_ONE_PERCENT" if abs(relative) <= .01 else "MARGINAL_DISCRETE_SAMPLE_ONE_TO_TWO_PERCENT" if abs(relative) <= .02 else "HARDFAIL_DISCRETE_SAMPLE_OVER_TWO_PERCENT"
    control_binding = receipt_control_binding(receipt, regular(args.source_control, "F3 source control"))
    static_post = {key: record(path, f"F3 {key} post") for key, path in static_paths.items()}
    if static_pre != static_post:
        raise RuntimeError("F3 static source changed during audit")
    report = {
        "schema": SCHEMA, "status": "COMPLETED_F3_S2_INITIAL_SUPPORT_AUDIT_V3", "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": PHYSICAL_CASE_ID,
        "gencase_binding": identity,
        "generated": generated,
        "fluid_blocks": blocks,
        "source": {"xml": static_pre["source_xml"], "control": static_pre["source_control"], "control_receipt_binding": control_binding},
        "receipt": {"status": receipt.get("status"), "returncode": receipt.get("returncode"), "output_root": receipt.get("output_root"), "input_hashes_at_launch": receipt.get("input_hashes_at_launch", "UNKNOWN")},
        "vtk_support": {"fluid": {**fluid_meta, "axis_summary": ROOT086.axis_summary(points), "owner_relation": {"owner_low_m": owner_low, "owner_high_m": owner_high, "tolerance_m": tol, "inside_owner_closed_count": int(inside.sum()), "outside_owner_closed_count": int((~inside).sum()), "physical_fate": "UNKNOWN"}, "input_record": dynamic_pre["fluid_vtk"]}, "bound": {**bound_meta, "axis_summary": ROOT086.axis_summary(bound_points), "input_record": dynamic_pre["bound_vtk"]}, "finite_points": bool(points.size and bound_points.size and __import__("numpy").isfinite(points).all() and __import__("numpy").isfinite(bound_points).all()), "pre_post_sha_stat_equal": True},
        "mass_audit": {"sample_mass_kg": generated["sample_mass_kg"], "continuous_owner_mass_kg": OWNER_MASS_KG, "relative_error_vs_owner_fraction": relative, "relative_error_vs_owner_percent": 100.0 * relative, "discrete_sample_gate": mass_gate, "mass_rescale": False, "continuous_mass_qualification": "UNKNOWN"},
        "input_stability": {"static_pre": static_pre, "static_post": static_post, "dynamic_pre": dynamic_pre, "dynamic_post": dynamic_post, "pre_post_sha_stat_equal": True, "worker_first_payload_hash_after_parent_reservation": True, "parent_dynamic_vtk_hash": "NOT_CLAIMED; worker-owned first/post hashes above"},
        "scope": {"gencase_rerun": False, "solver_started": False, "bi4_read": False, "hdf5_read": False, "generated_xml_read": True, "fluid_vtk_read": True, "bound_vtk_read": True},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "single source-bound GenCase initial support/Idp/axis/owner audit; particle sample and owner mass relation do not prove continuous equivalence, no-penetration, flux, or solver accuracy"},
    }
    return report


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable F3 v3 report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def self_test() -> dict[str, Any]:
    positive = ROOT086.self_test()
    if positive.get("status") != "PASS":
        raise AssertionError(positive)
    return {"status": "PASS", "schema": SCHEMA, "reused_root086_binary_vtk_parser": True, "worker_first_payload_hash_after_parent_reservation": True, "solver_started": False, "bi4_read": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for name in ("gencase-request", "receipt", "generated-xml", "fluid-vtk", "bound-vtk", "source-xml", "source-control", "support-contract", "output"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--expected-generated-xml-sha")
    parser.add_argument("--expected-support-contract-sha")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2)); return 0
    required = [args.gencase_request, args.receipt, args.generated_xml, args.fluid_vtk, args.bound_vtk, args.source_xml, args.source_control, args.support_contract, args.output]
    if any(value is None for value in required):
        parser.error("all q/receipt/generated/source/support-contract/output paths are required")
    report = build_report(args)
    write_new(args.output, report)
    print(json.dumps({"status": report["status"], "schema": SCHEMA, "output": str(args.output.resolve()), "fluid_count": report["generated"]["fluid_count"], "mass_gate": report["mass_audit"]["discrete_sample_gate"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
