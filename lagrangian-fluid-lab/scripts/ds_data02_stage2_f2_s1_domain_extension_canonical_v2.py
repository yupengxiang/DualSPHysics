#!/usr/bin/env python3
"""Make a root-owned canonical request for the F2 numerical-domain pair.

The existing v1 request and preparation manifest remain immutable.  This
forward-only wrapper verifies the candidate XML's one-face semantic change,
the exact initial-BI4/motion reuse, and the completed source receipt, then
emits a new v2 request with the source solver's CPU/GPU/resource-window
metadata copied as an auditable scheduling contract.  It never runs GenCase,
DualSPHysics, PartVTKOut, H5, or a CFD/model workload.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V1_CASE = "F2_S1_ORIGINAL_DP010_DOMAIN_XLOW_EXTENDED_V1"
V2_CASE = "F2_S1_ORIGINAL_DP010_DOMAIN_XLOW_EXTENDED_V2"
V2_ATTEMPT = "f2-s1-original-dp010-domain-xlow-extended-v2"
PHYSICAL_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
SOURCE_CASE = "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010"


class CanonicalError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise CanonicalError(f"{label} is missing: {path}")
    return path


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CanonicalError(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def semantic_xml(path: Path) -> bytes:
    root = ET.parse(path).getroot()
    return ET.tostring(root, encoding="utf-8")


def domain_values(path: Path) -> dict[str, dict[str, str]]:
    root = ET.parse(path).getroot()
    domain = next((node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "simulationdomain"), None)
    if domain is None:
        raise CanonicalError(f"simulationdomain is missing: {path}")
    result: dict[str, dict[str, str]] = {}
    for name in ("posmin", "posmax"):
        node = next((item for item in domain if item.tag.rsplit("}", 1)[-1] == name), None)
        if node is None or any(axis not in node.attrib for axis in "xyz"):
            raise CanonicalError(f"simulationdomain/{name} is incomplete: {path}")
        result[name] = {axis: node.attrib[axis] for axis in "xyz"}
    return result


def build(v1_path: Path, prepared_path: Path, source_receipt_path: Path, output: Path, evidence: Path | None) -> dict[str, Any]:
    v1_path, v1 = read_json(v1_path, "domain v1 request")
    prepared_path, prepared = read_json(prepared_path, "domain preparation manifest")
    source_receipt_path, source_receipt = read_json(source_receipt_path, "source solver receipt")
    if v1.get("schema") != "ds02.request.v1" or v1.get("case_id") != V1_CASE:
        raise CanonicalError("input request is not the preserved domain v1 request")
    if prepared.get("status") != "PREPARED_LAUNCH_DISABLED":
        raise CanonicalError("candidate preparation is not the launch-disabled manifest")
    if source_receipt.get("schema") != "ds02.execution-receipt.v1" or source_receipt.get("status") != "completed" or source_receipt.get("returncode") != 0:
        raise CanonicalError("source solver receipt is not completed code 0")
    source_request = source_receipt.get("request", {})
    if source_request.get("family_id") != "F2" or source_request.get("physical_case_id") != PHYSICAL_CASE:
        raise CanonicalError("source solver receipt physical identity differs")
    if source_request.get("case_id") != SOURCE_CASE:
        raise CanonicalError("source solver receipt is not the registered dp=0.01 source")
    candidate_xml = require_file(v1["command"][1] + ".xml", "candidate XML")
    candidate_bi4 = require_file(candidate_xml.with_suffix(".bi4"), "candidate initial BI4")
    candidate_motion = next(
        (require_file(item, "candidate motion") for item in v1.get("input_files", [])
         if Path(str(item)).parent == candidate_xml.parent and Path(str(item)).name.endswith("_motion.dat")),
        None,
    )
    if candidate_motion is None:
        raise CanonicalError("candidate motion symlink is not present in v1 input files")
    source_xml = require_file(v1["source_original_generated_xml"], "source XML")
    source_bi4 = require_file(v1["source_original_generated_bi4"], "source BI4")
    source_motion = require_file(v1["source_original_motion"], "source motion")
    if sha256(source_receipt_path) != v1.get("source_solver_receipt_sha256"):
        raise CanonicalError("v1 source solver receipt digest changed")
    declared = v1.get("input_sha256", {})
    for path, label in ((candidate_xml, "candidate XML"), (candidate_bi4, "candidate BI4"), (candidate_motion, "source motion"), (source_xml, "source XML"), (source_bi4, "source BI4"), (source_motion, "source motion")):
        expected = declared.get(str(path))
        if expected and expected != sha256(path):
            raise CanonicalError(f"{label} digest changed: {path}")
    source_bounds = domain_values(source_xml)
    candidate_bounds = domain_values(candidate_xml)
    if source_bounds["posmin"]["x"] != "-1.40" or candidate_bounds["posmin"]["x"] != "-1.60":
        raise CanonicalError("domain pair does not use the registered -1.40 -> -1.60 x-low values")
    changed: list[str] = []
    for name in ("posmin", "posmax"):
        for axis in "xyz":
            if source_bounds[name][axis] != candidate_bounds[name][axis]:
                changed.append(f"parameters/simulationdomain/{name}/@{axis}")
    if changed != ["parameters/simulationdomain/posmin/@x"]:
        raise CanonicalError(f"candidate domain changed unexpected fields: {changed}")
    if sha256(source_bi4) != v1["source_original_generated_bi4_sha256"] or sha256(source_motion) != v1["source_original_motion_sha256"]:
        raise CanonicalError("source immutable input digest differs from v1 binding")
    if candidate_bi4.resolve() != source_bi4.resolve() or candidate_motion.resolve() != source_motion.resolve():
        raise CanonicalError("candidate initial BI4 or motion is not the exact source symlink")
    source_sched_keys = (
        "resource_window", "root_dataset_inventory_profile", "root_gpu_selection_profile",
        "root_solver_concurrency_cap", "root_inventory_policy_source_sha256",
        "root_effective_reservation_function_sha256", "root_actual_launch_source",
        "root_actual_launch_source_sha256", "runtime_entrypoint", "runtime_sha256",
        "strict_dispatch_entrypoint", "strict_dispatch_sha256", "physical_window_s",
        "save_interval_s", "estimated_peak_gpu_mib", "max_wall_seconds", "launch_owner",
        "launch", "launch_allowed", "execution_allowed", "foreign_process_protection_required",
        "shared_lease_required", "kind", "cpu_task_kind", "cpu_threads", "omp_threads",
        "estimated_storage_bytes", "production_approval", "q_n", "precision_status",
    )
    scheduler_binding = {key: copy.deepcopy(source_request[key]) for key in source_sched_keys if key in source_request}
    request = copy.deepcopy(v1)
    request.update({
        "case_id": V2_CASE,
        "attempt_id": V2_ATTEMPT,
        "request_version": 2,
        "canonical_ready": True,
        "launch_disabled": False,
        "execution_allowed": True,
        "launch_allowed": True,
        "launch": True,
        "primary_launch_owner": "root",
        "launch_owner": "root",
        "shared_lease_required": True,
        "foreign_process_protection_required": True,
        "max_wall_seconds": int(source_request.get("max_wall_seconds", v1.get("max_wall_seconds", 7200))),
        "estimated_storage_bytes": int(source_request.get("estimated_storage_bytes", v1.get("estimated_storage_bytes", 10 * 2**30))),
        "estimated_peak_gpu_mib": int(source_request.get("estimated_peak_gpu_mib", 4096)),
        "resource_window": copy.deepcopy(source_request.get("resource_window", {})),
        "scheduler_binding": scheduler_binding,
        "supersedes": {"path": str(v1_path), "sha256": sha256(v1_path), "reason": "preserved v1; v2 adds canonical root CPU/GPU scheduling metadata"},
        "control_closure": {
            **copy.deepcopy(v1.get("control_closure", {})),
            "xml_semantic_changed_paths": changed,
            "initial_bi4_sha256": sha256(source_bi4),
            "motion_sha256": sha256(source_motion),
            "source_xml_sha256": sha256(source_xml),
            "candidate_xml_sha256": sha256(candidate_xml),
            "physical_wetted_wall_changed": False,
            "numeric_domain_only": True,
        },
        "request_note": (
            "Canonical-ready root-owned F2 paired numerical-domain diagnostic. The candidate XML changes "
            "only simulationdomain/posmin/@x from -1.40 to -1.60 m; XML semantics, initial BI4, motion, "
            "dp, CFL, and solver flags are source-bound. CPU/GPU/resource-window fields are copied from "
            "the completed source solver request. Preparation did not launch GenCase or DualSPHysics; "
            "physical fate, dynamics, QN, and QE remain unknown."
        ),
    })
    script_key = str(SCRIPT)
    files = list(request.get("input_files", []))
    if script_key not in files:
        files.append(script_key)
    request["input_files"] = sorted(set(files))
    digests = dict(request.get("input_sha256", {}))
    digests[script_key] = sha256(SCRIPT)
    request["input_sha256"] = {str(key): digests[str(key)] for key in request["input_files"]}
    if output.exists():
        old = json.loads(output.read_text(encoding="utf-8"))
        if old != request:
            raise CanonicalError(f"refusing to overwrite existing request: {output}")
    else:
        atomic_json(output, request)
    report = {
        "schema": "ds02.stage2.f2-s1-domain-extension-canonical-v2.v1",
        "status": "CANONICAL_READY",
        "request": {"path": str(output.resolve()), "sha256": sha256(output), "case_id": V2_CASE, "attempt_id": V2_ATTEMPT},
        "preserved_v1_request": {"path": str(v1_path), "sha256": sha256(v1_path)},
        "source_solver_receipt": {"path": str(source_receipt_path), "sha256": sha256(source_receipt_path)},
        "domain_semantic_diff": {"changed_paths": changed, "source_bounds": source_bounds, "candidate_bounds": candidate_bounds, "xml_only_numeric_domain": True},
        "immutable_reuse": {
            "source_bi4": {"path": str(source_bi4), "sha256": sha256(source_bi4)},
            "candidate_bi4": {"path": str(candidate_bi4), "sha256": sha256(candidate_bi4), "same_target": candidate_bi4.resolve() == source_bi4.resolve()},
            "source_motion": {"path": str(source_motion), "sha256": sha256(source_motion)},
            "candidate_motion": {"path": str(candidate_motion), "sha256": sha256(candidate_motion), "same_target": candidate_motion.resolve() == source_motion.resolve()},
        },
        "scheduler_binding": scheduler_binding,
        "read_policy": {"h5_opened": False, "gencase_started": False, "solver_started": False, "partvtkout_started": False, "cfd_or_model_run": False},
        "qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }
    if evidence is not None:
        atomic_json(evidence, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-request", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    try:
        report = build(args.v1_request, args.prepared, args.source_receipt, args.output, args.evidence)
    except CanonicalError as exc:
        raise SystemExit(f"CanonicalError: {exc}")
    print(json.dumps({"status": report["status"], "request": report["request"], "evidence": str(args.evidence.resolve()) if args.evidence else None}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
