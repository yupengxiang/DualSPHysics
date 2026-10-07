#!/usr/bin/env python3
"""Prepare a second bounded mass-fit bracket from actual v1 GenCase mass.

The v1 cubic prediction is treated as a measured bracket endpoint, not as a
successful mass match.  This v2 module registers one forward-only probe for
every v1 result outside the adopted one-percent target (five marginal and four
hard results).  It keeps the original source Def and motion assets immutable,
changes only ``definition@dp``, and binds each request to the v1 generated XML
and receipt that supplied the new prediction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any


REPO = Path(__file__).resolve().parents[5]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
QUALITY_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_reference_quality_cost_v2.json"
SPATIAL_MANIFEST_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_remaining_sentinel_spatial_preflight_inputs_v1/manifest.json"
V1_MANIFEST_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_mass_fit_probe_inputs_v1/manifest.json"
V1_RESULTS_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_mass_fit_probe_results_v1.json"
REVIEW_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"
CURRENT_PATH = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
V1_REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-mass-fit-probe-v1"
INPUT_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_mass_fit_probe_inputs_v2"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-mass-fit-probe-v2"
MiB = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def atomic_write(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def normalized_geometry_hash(data: bytes) -> str:
    normalized, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb'\1<DP>\2', data, count=1)
    if count != 1:
        raise ValueError("expected one definition@dp")
    return hashlib.sha256(normalized).hexdigest()


def load_sources() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    results = json.loads(V1_RESULTS_PATH.read_text(encoding="utf-8"))
    prep = json.loads(V1_MANIFEST_PATH.read_text(encoding="utf-8"))
    quality = json.loads(QUALITY_PATH.read_text(encoding="utf-8"))
    if results.get("schema") != "ds02.stage2.mass-fit-probe-results.v1":
        raise ValueError("unexpected v1 result schema")
    return results, prep, quality


def predecessor_requests() -> dict[str, dict[str, Any]]:
    result = {}
    for path in V1_REQUEST_ROOT.glob("*.json"):
        request = json.loads(path.read_text(encoding="utf-8"))
        result[request["case_id"]] = {"path": path, "request": request}
    return result


def case_id(sid: str, label: str, dp: float) -> str:
    return f"{sid.replace('-', '_')}_MASSFIT_V2_{label.upper()}_DP{dp:.6f}".replace(".", "p")


def copy_inputs(source_def: Path, deps: list[dict[str, Any]], case_dir: Path, dp: float) -> tuple[Path, list[dict[str, Any]]]:
    source = source_def.read_bytes()
    updated, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', lambda m: m.group(1) + f"{dp:.15g}".encode() + m.group(2), source, count=1)
    if count != 1:
        raise ValueError(f"source Def dp not unique: {source_def}")
    definition = case_dir / f"{case_dir.name}_Def.xml"
    atomic_write(definition, updated)
    derived = []
    for item in deps:
        relative = Path(item["relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe dependency {relative}")
        destination = case_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(destination)
        source_path = Path(item["source"]["path"])
        shutil.copyfile(source_path, destination)
        dest_record = record(destination)
        derived.append({"reference": item["reference"], "relative_path": relative.as_posix(), "source": record(source_path), "derived": dest_record, "byte_identical": dest_record["sha256"] == item["source"]["sha256"]})
    if normalized_geometry_hash(source) != normalized_geometry_hash(updated):
        raise ValueError("normalized source geometry changed")
    return definition, derived


def prepare() -> dict[str, Any]:
    results, v1_prep, quality = load_sources()
    v1_records = {item["candidate"]["case_id"]: item for item in v1_prep["records"]}
    quality_by_key = {(row["sentinel_id"], row["label"]): row for row in quality["candidate_quality_and_controls"]}
    v1_requests = predecessor_requests()
    selected = [item for item in results["results"] if item["mass_gate"]["gate"] != "PASS_TARGET_1PCT"]
    if len(selected) != 9:
        raise ValueError(f"expected 9 non-target v1 results, found {len(selected)}")
    source_head = git_commit()
    INPUT_ROOT.mkdir(parents=True, exist_ok=False)
    records = []
    for previous in selected:
        previous_case = previous["case_id"]
        old = v1_records.get(previous_case)
        if old is None:
            raise ValueError(f"v1 preparation record missing {previous_case}")
        sid, label = previous["sentinel_id"], previous["label"]
        qrow = quality_by_key[(sid, label)]
        source_mass = float(qrow["mass_diagnostic"]["source_sample_mass_kg"])
        actual_mass = float(previous["mass_gate"]["actual_generated_xml_sample_mass_kg"])
        old_dp = float(previous["prediction"]["predicted_dp_m"])
        target_dp = old_dp * (source_mass / actual_mass) ** (1.0 / 3.0)
        cid = case_id(sid, label, target_dp)
        case_dir = INPUT_ROOT / sid.replace("-", "_") / label
        case_dir.mkdir(parents=True, exist_ok=False)
        binding = old["candidate"]["source_binding"]
        source_def = Path(binding["source_definition"]["path"]).resolve()
        deps = binding.get("relative_dependencies", [])
        for path in (source_def, Path(binding["generated_xml"]["path"]), Path(binding["generated_bi4"]["path"]), Path(binding["gencase_receipt"]["path"]), Path(binding["solver_receipt"]["path"])):
            record(path)
        definition, derived_deps = copy_inputs(source_def, deps, case_dir, target_dp)
        predecessor = v1_requests.get(previous_case)
        if predecessor is None:
            raise ValueError(f"v1 request missing {previous_case}")
        predecessor_receipt = Path(previous["receipt"]["path"])
        predecessor_xml = Path(previous["generated_xml"]["path"])
        predecessor_bi4 = Path(previous["generated_bi4"]["path"])
        for path in (predecessor["path"], predecessor_receipt, predecessor_xml, predecessor_bi4):
            record(path)
        source_dp = float(binding["source_definition"].get("dp_m", binding.get("source_dp_m", 0.0)) or 0.0)
        if not source_dp:
            # The exact historical generated XML is the source numerical dp.
            text = Path(binding["generated_xml"]["path"]).read_text(encoding="utf-8")
            match = re.search(r'<definition\b[^>]*\bdp="([^"]+)"', text)
            if not match:
                raise ValueError(f"source generated XML dp missing {sid}")
            source_dp = float(match.group(1))
        ratio = source_dp / target_dp
        source_bytes = int(binding["generated_bi4"]["bytes"]) + int(binding["generated_xml"]["bytes"])
        dep_bytes = sum(int(item["source"]["bytes"]) for item in deps)
        estimate = max(128 * MiB, int(math.ceil((source_bytes * ratio ** 3 + dep_bytes + definition.stat().st_size + 32 * MiB) * 2.5 / MiB) * MiB))
        candidate = {
            "schema": "ds02.stage2.mass-fit-probe.v2",
            "case_id": cid,
            "sentinel_id": sid,
            "family_id": old["candidate"]["family_id"],
            "physical_case_id": old["candidate"]["physical_case_id"],
            "label": label,
            "prediction": {"formula": "v1_actual_dp * (source_sample_mass_kg / v1_actual_generated_xml_sample_mass_kg)^(1/3)", "source_sample_mass_kg": source_mass, "v1_actual_generated_xml_sample_mass_kg": actual_mass, "v1_actual_deviation_pct": previous["mass_gate"]["deviation_pct_vs_source"], "v1_actual_dp_m": old_dp, "predicted_dp_m": target_dp, "source_dp_m": source_dp, "actual_mass_gate": "UNKNOWN_UNTIL_GENERATED_XML"},
            "predecessor": {"case_id": previous_case, "request": record(predecessor["path"]), "receipt": record(predecessor_receipt), "generated_xml": record(predecessor_xml), "generated_bi4": record(predecessor_bi4)},
            "source_binding": {"generated_xml": record(Path(binding["generated_xml"]["path"])), "generated_bi4": record(Path(binding["generated_bi4"]["path"])), "gencase_receipt": record(Path(binding["gencase_receipt"]["path"])), "solver_receipt": record(Path(binding["solver_receipt"]["path"])), "source_definition": record(source_def), "relative_dependencies": [{"reference": item["reference"], "relative_path": item["relative_path"], "source": item["source"]} for item in deps], "source_producer_vs_current_head": source_head},
            "derived_inputs": {"definition": record(definition), "relative_dependencies": derived_deps},
            "continuous_vs_intentional": {"source_definition_normalized_hash": normalized_geometry_hash(source_def.read_bytes()), "derived_definition_normalized_hash": normalized_geometry_hash(definition.read_bytes()), "draw_fill_domain_geometry_changed": False, "motion_or_acceleration_changed": False, "dependencies_byte_identical": all(item["byte_identical"] for item in derived_deps), "intentional_changes": ["dp", "h/massfluid/count/lattice phase measured after GenCase"]},
            "historical_controls": old["candidate"].get("historical_controls", {}),
            "floating_mass_semantics": old["candidate"].get("floating_mass_semantics", "sample mass and rigid body mass are separate"),
            "estimated_storage_bytes": estimate,
            "status": "PREPARED_GENCASE_INPUT_NOT_RUN",
            "solver_started": False,
            "full_time_hdf5_read": False,
            "gpu_lease": "none",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        }
        records.append({"candidate": candidate, "aux": {"definition": record(definition), "dependencies": derived_deps}})
    manifest = {"schema": "ds02.stage2.mass-fit-probe-inputs.v2", "status": "PREPARED_GENCASE_INPUTS_NOT_RUN", "generated_at_commit": source_head, "quality_source": record(QUALITY_PATH), "spatial_source": record(SPATIAL_MANIFEST_PATH), "v1_results": record(V1_RESULTS_PATH), "v1_manifest": record(V1_MANIFEST_PATH), "target_policy": "one forward bounded bracket per v1 result outside PASS_TARGET_1PCT; no threshold relaxation", "target_count": len(records), "records": records, "solver_started": False, "full_time_hdf5_read": False, "gpu_lease": "none", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    write_json(INPUT_ROOT / "manifest.json", manifest)
    return manifest


def request_for(candidate: dict[str, Any], aux: dict[str, Any], manifest_path: Path, source_head: str) -> dict[str, Any]:
    source = candidate["source_binding"]
    predecessor = candidate["predecessor"]
    paths = [
        PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py",
        PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py",
        PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py",
        PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_mass_fit_probe_v2.py",
        GENCASE, CURRENT_PATH, REVIEW_PATH, QUALITY_PATH, QUALITY_PATH.with_suffix(".json"), SPATIAL_MANIFEST_PATH, V1_MANIFEST_PATH, V1_RESULTS_PATH,
        Path(predecessor["request"]["path"]), Path(predecessor["receipt"]["path"]), Path(predecessor["generated_xml"]["path"]), Path(predecessor["generated_bi4"]["path"]),
        Path(source["generated_xml"]["path"]), Path(source["generated_bi4"]["path"]), Path(source["gencase_receipt"]["path"]), Path(source["solver_receipt"]["path"]), Path(source["source_definition"]["path"]), aux["definition"],
    ]
    paths.extend(Path(item["derived"]["path"]) for item in aux["dependencies"])
    unique = []
    seen = set()
    for path in paths:
        path = path.resolve()
        if str(path) in seen:
            continue
        if not path.is_file():
            raise FileNotFoundError(path)
        unique.append(path)
        seen.add(str(path))
    hashes = {str(path): sha256_file(path) for path in unique}
    return {"schema": "ds02.request.v1", "family_id": candidate["family_id"], "case_id": candidate["case_id"], "attempt_id": candidate["case_id"].lower() + "-001", "kind": "cpu", "cpu_task_kind": "gencase", "cpu_threads": 2, "max_wall_seconds": 900, "estimated_storage_bytes": candidate["estimated_storage_bytes"], "worktree_root": str(REPO), "cwd": str(aux["definition"].parent), "command": [str(GENCASE), str(aux["definition"].with_suffix("")), "{attempt_root}/generated", "-save:all"], "input_files": [str(path) for path in unique], "input_hashes": hashes, "input_sha256": hashes, "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"), "strict_guard": str(PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"), "runtime": str(PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"), "launch_commit": source_head, "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "estimated_cpu_core_hours": 0.5, "estimated_new_storage_bytes": candidate["estimated_storage_bytes"]}, "source_binding": source, "predecessor": candidate["predecessor"], "mass_fit_prediction": candidate["prediction"], "scope": {"sentinel_id": candidate["sentinel_id"], "physical_case_id": candidate["physical_case_id"], "continuous_geometry_control": candidate["continuous_vs_intentional"], "historical_controls": candidate["historical_controls"], "gencase_only": True, "mass_gate": "UNKNOWN_UNTIL_GENERATED_XML", "solver_started": False, "full_time_hdf5_read": False, "gpu_uuid_lease": "none", "scientific_qualification": "UNKNOWN"}, "preparation_manifest": str(manifest_path.resolve()), "status": "READY_FOR_PARENT_CPU_GUARD_REVIEW"}


def emit(manifest: dict[str, Any]) -> int:
    REQUEST_ROOT.mkdir(parents=True, exist_ok=False)
    count = 0
    for item in manifest["records"]:
        candidate = item["candidate"]
        aux = {"definition": Path(item["aux"]["definition"]["path"]), "dependencies": item["aux"]["dependencies"]}
        write_json(REQUEST_ROOT / f"{candidate['case_id'].lower()}.json", request_for(candidate, aux, INPUT_ROOT / "manifest.json", manifest["generated_at_commit"]))
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--emit-requests", action="store_true")
    args = parser.parse_args()
    if not args.prepare and not args.emit_requests:
        raise SystemExit("choose --prepare and/or --emit-requests")
    manifest = prepare() if args.prepare else json.loads((INPUT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    count = emit(manifest) if args.emit_requests else 0
    print(json.dumps({"status": "PASS", "targets": manifest["target_count"], "requests": count, "manifest": str(INPUT_ROOT / "manifest.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
