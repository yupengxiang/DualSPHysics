#!/usr/bin/env python3
"""Audit the bounded F4--F7 GenCase-only spatial preflight receipts.

The audit is forward-only and consumes the immutable v1 manifest, requests,
candidate inputs, and terminal guard receipts.  It verifies source/derived
identity, dependency byte preservation, generated particle summaries, and the
actual output-tree size against each registered reservation.  It does not
read native HDF5, run a solver, or assign QI/QN/QE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from xml.etree import ElementTree as ET


REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
MANIFEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_remaining_sentinel_spatial_preflight_inputs_v1/manifest.json"
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-remaining-sentinel-spatial-preflight-v1"
WRAPPER = Path(__file__).resolve()
SCHEMA = "ds02.stage2.remaining-sentinel-spatial-audit.v1"
REQUEST_SCHEMA = "ds02.request.v1"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def tree_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def tag(element: ET.Element) -> str:
    return element.tag.split("}")[-1].lower()


def numeric_values(root: ET.Element, element_tag: str, attribute: str) -> list[str]:
    return [element.attrib[attribute] for element in root.iter() if tag(element) == element_tag and attribute in element.attrib]


def parameter_values(root: ET.Element, key: str) -> list[str]:
    return [element.attrib["value"] for element in root.iter() if tag(element) == "parameter" and element.attrib.get("key") == key and "value" in element.attrib]


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def numeric_or_unknown(values: list[str]) -> str:
    values = unique(values)
    if not values:
        return "UNKNOWN"
    try:
        numbers = [float(value) for value in values]
    except (TypeError, ValueError):
        return values[0] if len(values) == 1 else "UNKNOWN_CONFLICT"
    if max(numbers) - min(numbers) > 1e-12:
        return "UNKNOWN_CONFLICT"
    return format(numbers[0], ".15g")


def fluid_summary(root: ET.Element) -> dict[str, Any]:
    fluids = []
    floatings = []
    for element in root.iter():
        if tag(element) == "fluid" and "mkfluid" in element.attrib and "count" in element.attrib:
            try:
                count: int | str = int(element.attrib["count"])
            except ValueError:
                count = "UNKNOWN"
            fluids.append({"mkfluid": element.attrib["mkfluid"], "count": count})
        if tag(element) == "floating" and "count" in element.attrib:
            try:
                count = int(element.attrib["count"])
            except ValueError:
                count = "UNKNOWN"
            floatings.append({"mkbound": element.attrib.get("mkbound", "UNKNOWN"), "count": count})
    mass_values = numeric_values(root, "massfluid", "value")
    result: dict[str, Any] = {"fluid_blocks": fluids, "floating_blocks": floatings, "massfluid_values": mass_values}
    try:
        count = sum(int(item["count"]) for item in fluids)
        mass = float(numeric_or_unknown(mass_values))
        result["total_fluid_particles"] = count
        result["sample_mass_kg"] = count * mass
    except (TypeError, ValueError):
        result["sample_mass_kg"] = "UNKNOWN"
    result["rigid_body_massbody_kg"] = numeric_or_unknown(numeric_values(root, "massbody", "value"))
    result["rigid_body_inertia"] = {axis: numeric_or_unknown(numeric_values(root, "inertia", axis)) for axis in ("x", "y", "z")}
    result["floating_particle_masspart_kg"] = numeric_or_unknown(
        [element.attrib[key] for element in root.iter() for key in ("masspart", "MassBound") if key in element.attrib]
        + numeric_values(root, "masspart", "value")
    )
    result["floating_sample_mass_kg"] = "UNKNOWN"
    result["floating_mass_semantics"] = "particle sample mass is separate from rigid massbody/inertia; no substitution is made"
    return result


def normalized_definition_hash(path: Path) -> str:
    data = path.read_bytes()
    normalized, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb'\1<DP>\2', data, count=1)
    if count != 1:
        raise ValueError(f"candidate Def has no unique definition@dp: {path}")
    return hashlib.sha256(normalized).hexdigest()


def candidate_audit(candidate: dict[str, Any], request: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    family = candidate["family_id"]
    case = candidate["case_id"]
    attempt = request["attempt_id"]
    output_root = DATA_ROOT / "families" / family / case / attempt
    receipt_path = output_root / "execution-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    output_files = sorted(path for path in output_root.iterdir() if path.is_file())
    generated_xml = output_root / "generated.xml"
    generated_bi4 = output_root / "generated.bi4"
    generated_bytes, generated_root = (generated_xml.read_bytes(), ET.fromstring(generated_xml.read_bytes())) if generated_xml.is_file() else (b"", None)
    problems: list[str] = []
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0 or receipt.get("termination_reason") is not None:
        problems.append("terminal receipt is not completed with returncode 0")
    actual_bytes = tree_bytes(output_root)
    if actual_bytes > request["estimated_storage_bytes"]:
        problems.append("actual output tree exceeds registered storage reservation")
    if generated_root is None or not generated_bi4.is_file():
        problems.append("GenCase generated.xml/generated.bi4 missing")
    request_hashes = receipt.get("input_hashes_at_launch", {})
    after_hashes = receipt.get("input_hashes_after_run", {})
    if request_hashes != after_hashes:
        problems.append("guard input digest changed during run")
    input_def = Path(candidate["derived_inputs"]["definition"]["path"])
    if not input_def.is_file():
        problems.append("derived Def input missing")
    else:
        if sha256_file(input_def) != candidate["derived_inputs"]["definition"]["sha256"]:
            problems.append("derived Def digest differs from manifest")
        if normalized_definition_hash(input_def) != candidate["continuous_geometry_control"]["source_definition_normalized_hash"]:
            problems.append("derived Def normalized geometry hash differs from source")
    dependency_checks = []
    for item in candidate["derived_inputs"]["relative_dependencies"]:
        derived = Path(item["derived"]["path"])
        ok = derived.is_file() and sha256_file(derived) == item["source"]["sha256"] == item["derived"]["sha256"]
        dependency_checks.append({"relative_path": item["relative_path"], "derived": file_record(derived) if derived.is_file() else None, "byte_identical": ok})
        if not ok:
            problems.append(f"dependency digest mismatch: {item['relative_path']}")
    actual_meta: dict[str, Any] = {}
    if generated_root is not None:
        summary = fluid_summary(generated_root)
        actual_meta = {
            "definition_dp_m": numeric_or_unknown(numeric_values(generated_root, "definition", "dp")),
            "h_m": numeric_or_unknown(numeric_values(generated_root, "h", "value")),
            "particles": numeric_or_unknown(numeric_values(generated_root, "particles", "np")),
            "cflnumber": numeric_or_unknown(numeric_values(generated_root, "cflnumber", "value")),
            "parameters": {key: numeric_or_unknown(parameter_values(generated_root, key)) for key in ("DtMin", "DtFixed", "TimeMax", "TimeOut")},
            "mass_semantics": summary,
            "generated_xml": file_record(generated_xml),
            "generated_bi4": file_record(generated_bi4) if generated_bi4.is_file() else None,
        }
        if actual_meta["definition_dp_m"] != format(float(candidate["dp_m"]), ".15g"):
            problems.append("generated definition dp differs from request candidate dp")
        if receipt.get("total_particles") != summary.get("particles", summary.get("total_fluid_particles")) and receipt.get("total_particles") != int(float(actual_meta["particles"])):
            problems.append("receipt total particle count differs from generated XML")
        if receipt.get("fluid_particles") != summary.get("total_fluid_particles"):
            problems.append("receipt fluid particle count differs from generated XML")
    return {
        "sentinel_id": candidate["sentinel_id"],
        "family_id": family,
        "physical_case_id": candidate["physical_case_id"],
        "candidate_id": case,
        "label": candidate["label"],
        "request_path": str((REQUEST_DIR / (case.lower() + ".json")).resolve()),
        "receipt_path": str(receipt_path.resolve()),
        "receipt_status": receipt.get("status"),
        "receipt_returncode": receipt.get("returncode"),
        "receipt_termination_reason": receipt.get("termination_reason"),
        "receipt_elapsed_seconds": receipt.get("elapsed_seconds"),
        "receipt_cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "receipt_total_particles": receipt.get("total_particles"),
        "receipt_fluid_particles": receipt.get("fluid_particles"),
        "actual_output_tree_bytes": actual_bytes,
        "reserved_output_tree_bytes": request["estimated_storage_bytes"],
        "storage_utilization": actual_bytes / request["estimated_storage_bytes"] if request["estimated_storage_bytes"] else "UNKNOWN",
        "output_files": [file_record(path) for path in output_files],
        "actual_generated_xml": actual_meta,
        "dependency_checks": dependency_checks,
        "input_digest_stable": request_hashes == after_hashes,
        "status": "PASS_GENCAS_SOURCE_BOUND" if not problems else "FAIL_AUDIT",
        "problems": problems,
        "scientific_qualification": "UNKNOWN",
        "QI": "NOT_ASSESSED",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
    }


def audit(output: Path, manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = []
    request_commit_set = set()
    for sentinel in manifest["sentinels"]:
        for candidate in sentinel["candidates"]:
            request_path = REQUEST_DIR / (candidate["case_id"].lower() + ".json")
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request_commit_set.add(request["resource_guard"]["launch_commit"])
            results.append(candidate_audit(candidate, request, manifest_path))
    actual_total = sum(row["actual_output_tree_bytes"] for row in results)
    reserve_total = sum(row["reserved_output_tree_bytes"] for row in results)
    result = {
        "schema": SCHEMA,
        "status": "PASS" if all(row["status"] == "PASS_GENCAS_SOURCE_BOUND" for row in results) else "FAIL",
        "source_manifest": file_record(manifest_path),
        "audit_wrapper": file_record(WRAPPER),
        "audit_current_head": git_commit(),
        "request_launch_commits": sorted(request_commit_set),
        "target_sentinels": manifest["target_sentinels"],
        "candidate_count": len(results),
        "completed_count": sum(row["status"] == "PASS_GENCAS_SOURCE_BOUND" for row in results),
        "actual_output_tree_bytes": actual_total,
        "reserved_output_tree_bytes": reserve_total,
        "storage_utilization": actual_total / reserve_total if reserve_total else "UNKNOWN",
        "solver_started": False,
        "full_time_hdf5_read": False,
        "scientific_qualification": "UNKNOWN",
        "results": results,
    }
    atomic_json(output, result)
    print(json.dumps({"status": result["status"], "output": str(output), "candidates": len(results), "completed": result["completed_count"], "actual_bytes": actual_total}, ensure_ascii=False))


def build_request(output_dir: Path, manifest_path: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs: list[Path] = [WRAPPER, manifest_path, REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py", REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py", REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"]
    for sentinel in json.loads(manifest_path.read_text(encoding="utf-8"))["sentinels"]:
        for candidate in sentinel["candidates"]:
            request_path = REQUEST_DIR / (candidate["case_id"].lower() + ".json")
            request = json.loads(request_path.read_text(encoding="utf-8"))
            receipt_path = DATA_ROOT / "families" / request["family_id"] / request["case_id"] / request["attempt_id"] / "execution-receipt.json"
            output_root = receipt_path.parent
            inputs.extend([request_path, receipt_path])
            inputs.extend(path for path in output_root.iterdir() if path.is_file() and path.name in {"generated.xml", "generated.bi4", "stdout.log"})
            inputs.append(Path(candidate["derived_inputs"]["definition"]["path"]))
            inputs.extend(Path(item["derived"]["path"]) for item in candidate["derived_inputs"]["relative_dependencies"])
    unique: list[Path] = []
    seen: set[str] = set()
    for path in inputs:
        path = path.resolve()
        if str(path) not in seen:
            if not path.is_file():
                raise FileNotFoundError(path)
            unique.append(path)
            seen.add(str(path))
    request = {
        "schema": REQUEST_SCHEMA,
        "family_id": "infra",
        "case_id": "STAGE2_REMAINING_SENTINEL_SPATIAL_AUDIT_V1",
        "attempt_id": "stage2-remaining-sentinel-spatial-audit-v1-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": [str(PYTHON), str(WRAPPER), "--audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/remaining-sentinel-audit-v1.json"],
        "input_files": [str(path) for path in unique],
        "input_hashes": {str(path): sha256_file(path) for path in unique},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "ds_data02_stage2_dispatch.py",
            "strict_guard": "ds_data02_strict_dispatch_v1.py",
            "runtime": "ds_data02_runtime_v2.py",
            "launch_commit": git_commit(),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "estimated_cpu_core_hours": 2 * 600 / 3600,
            "estimated_new_storage_bytes": 64 * 1024 * 1024,
        },
        "scope": {
            "audit": "F4-F7 source-bound GenCase terminal receipts and actual output-tree bytes",
            "gencase_only": True,
            "solver_started": False,
            "full_time_hdf5_read": False,
            "scientific_qualification": "UNKNOWN",
        },
    }
    atomic_json(output_dir / "stage2-remaining-sentinel-spatial-audit-v1.json", request)
    print(json.dumps({"status": "PASS", "request": str(output_dir / "stage2-remaining-sentinel-spatial-audit-v1.json"), "inputs": len(unique)}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--build-request-dir", type=Path)
    args = parser.parse_args()
    if args.audit:
        if args.output is None:
            raise SystemExit("--audit requires --output")
        audit(args.output, args.manifest)
        return 0
    if args.build_request_dir is None:
        raise SystemExit("choose --audit or --build-request-dir")
    build_request(args.build_request_dir, args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
