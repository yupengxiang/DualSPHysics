#!/usr/bin/env python3
"""Prepare source-bound, GenCase-only mass-fit probes for hard spatial grids.

The existing coarse/fine candidates deliberately span a useful resolution
ladder, but twelve F4--F7 candidates miss the pre-registered initial fluid
mass gate by more than two percent.  This module derives one bounded probe for
each such row using the measured candidate mass and the cubic spacing scaling
as a prediction.  GenCase is the authority: a change in lattice count or
phase is recorded rather than silently corrected.

Only ``definition@dp`` is changed in a copied source Def.  Continuous
draw/fill/domain geometry, controls, and referenced motion assets remain byte
identical.  The requests are CPU GenCase requests; this module never starts a
solver, reads a trajectory HDF5 file, or assigns scientific qualification.
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
from xml.etree import ElementTree as ET


SCHEMA = "ds02.stage2.mass-fit-probe.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CURRENT_PATH = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
REVIEW_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"
QUALITY_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_reference_quality_cost_v2.json"
SPATIAL_MANIFEST_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_remaining_sentinel_spatial_preflight_inputs_v1/manifest.json"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
INPUT_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_mass_fit_probe_inputs_v1"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-mass-fit-probe-v1"
DISPATCH = REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py"
STRICT = REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME = REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
MiB = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def atomic_write(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing file: {path}")
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


def numeric(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalized_geometry_hash(data: bytes) -> str:
    normalized, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb'\1<DP>\2', data, count=1)
    if count != 1:
        raise ValueError("expected one definition@dp in source Def")
    return hashlib.sha256(normalized).hexdigest()


def candidate_id(sid: str, label: str, dp: float) -> str:
    return f"{sid.replace('-', '_')}_MASSFIT_V1_{label.upper()}_DP{dp:.6f}".replace(".", "p")


def load_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    quality = json.loads(QUALITY_PATH.read_text(encoding="utf-8"))
    spatial = json.loads(SPATIAL_MANIFEST_PATH.read_text(encoding="utf-8"))
    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    if quality.get("schema") != "ds02.stage2.reference-quality-cost.v2":
        raise ValueError(f"unexpected quality schema: {quality.get('schema')}")
    return quality, spatial, {row["sentinel_id"]: row for row in review.get("sentinels", [])}


def hard_rows(quality: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        row for row in quality.get("candidate_quality_and_controls", [])
        if row.get("sentinel_id", "").startswith(("F4-", "F5-", "F6-", "F7-"))
        and row.get("mass_diagnostic", {}).get("gate") == "HARD_FAIL_GT2PCT"
    ]
    if len(rows) != 12:
        raise ValueError(f"expected 12 F4-F7 hard rows, found {len(rows)}")
    return rows


def spatial_by_id(spatial: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {row["sentinel_id"]: row for row in spatial.get("sentinels", [])}
    expected = {f"F{family}-S{slot}" for family in range(4, 8) for slot in (1, 2)}
    if not expected.issubset(rows):
        raise ValueError(f"spatial manifest missing {sorted(expected - set(rows))}")
    return rows


def review_identity(review_rows: dict[str, Any], sid: str, spatial_row: dict[str, Any]) -> None:
    review = review_rows.get(sid)
    if not review:
        raise ValueError(f"missing review identity for {sid}")
    if review.get("family") != spatial_row.get("family_id"):
        raise ValueError(f"family mismatch for {sid}")
    if review.get("source_physical_case_id") != spatial_row.get("physical_case_id"):
        raise ValueError(f"physical identity mismatch for {sid}")


def copy_derived_inputs(source_def: Path, dependencies: list[dict[str, Any]], case_dir: Path, dp: float) -> tuple[Path, list[dict[str, Any]]]:
    source_bytes = source_def.read_bytes()
    updated, count = re.subn(
        rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)',
        lambda match: match.group(1) + f"{dp:.15g}".encode("ascii") + match.group(2),
        source_bytes,
        count=1,
    )
    if count != 1:
        raise ValueError(f"source Def has no unique definition@dp: {source_def}")
    definition = case_dir / f"{case_dir.name}_Def.xml"
    atomic_write(definition, updated)
    derived_dependencies: list[dict[str, Any]] = []
    for item in dependencies:
        relative = Path(item["relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe dependency path {relative}")
        destination = case_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(destination)
        source = Path(item["source"]["path"])
        shutil.copyfile(source, destination)
        derived = record(destination)
        derived_dependencies.append({
            "reference": item["reference"],
            "relative_path": relative.as_posix(),
            "source": record(source),
            "derived": derived,
            "byte_identical": derived["sha256"] == item["source"]["sha256"],
        })
    return definition, derived_dependencies


def source_controls(sentinel: dict[str, Any]) -> dict[str, Any]:
    controls = sentinel.get("historical_solver_controls", {})
    return {
        "historical_solver_tmax_s": controls.get("effective_time_controls", {}).get("time_max_s", "UNKNOWN"),
        "historical_solver_tout_s": controls.get("effective_time_controls", {}).get("output_cadence_s", "UNKNOWN"),
        "xml_controls": controls.get("xml_controls", {}),
        "argv_controls": controls.get("solver_argv_controls", {}),
        "status": controls.get("status", "UNKNOWN"),
    }


def make_candidate(row: dict[str, Any], spatial: dict[str, Any], review_rows: dict[str, Any], source_head: str) -> tuple[dict[str, Any], dict[str, Any]]:
    sid = row["sentinel_id"]
    label = row["label"]
    md = row["mass_diagnostic"]
    source_mass = float(md["source_sample_mass_kg"])
    old_mass = float(md["candidate_sample_mass_kg"])
    old_dp = float(row["requested_dp_m"])
    target_dp = old_dp * (source_mass / old_mass) ** (1.0 / 3.0)
    # Keep enough digits for the source-derived prediction; the generated XML
    # and its particle count remain the authority.
    case = candidate_id(sid, label, target_dp)
    case_dir = INPUT_ROOT / sid.replace("-", "_") / label
    case_dir.mkdir(parents=True, exist_ok=False)
    source_binding = spatial["source_binding"]
    source_def = Path(source_binding["source_definition"]["path"]).resolve()
    generated = Path(source_binding["generated_xml"]["path"]).resolve()
    generated_bi4 = Path(source_binding["generated_bi4"]["path"]).resolve()
    gencase_receipt = Path(source_binding["gencase_receipt"]["path"]).resolve()
    solver_receipt = Path(source_binding["solver_receipt"]["path"]).resolve()
    for path in (source_def, generated, generated_bi4, gencase_receipt, solver_receipt):
        record(path)
    dependencies = source_binding.get("relative_dependencies", [])
    definition, derived_deps = copy_derived_inputs(source_def, dependencies, case_dir, target_dp)
    source_def_bytes = source_def.read_bytes()
    derived_bytes = definition.read_bytes()
    if normalized_geometry_hash(source_def_bytes) != normalized_geometry_hash(derived_bytes):
        raise ValueError(f"normalized geometry changed for {case}")
    if any(not item["byte_identical"] for item in derived_deps):
        raise ValueError(f"dependency changed for {case}")
    if not source_def.is_file() or not definition.is_file():
        raise ValueError(case)
    source_dp = numeric(spatial["generated_xml_meta"].get("dp_m"))
    if source_dp is None:
        raise ValueError(f"source dp unknown for {sid}")
    ratio = source_dp / target_dp
    source_generated_bytes = int(source_binding["generated_bi4"]["bytes"]) + int(source_binding["generated_xml"]["bytes"])
    dep_bytes = sum(int(item["source"]["bytes"]) for item in dependencies)
    raw_estimate = source_generated_bytes * ratio ** 3 + dep_bytes + definition.stat().st_size
    estimated_storage = max(64 * MiB, int(math.ceil((raw_estimate * 2.5 + 32 * MiB) / MiB) * MiB))
    review = review_rows[sid]
    review_identity(review_rows, sid, spatial)
    candidate = {
        "schema": SCHEMA,
        "case_id": case,
        "sentinel_id": sid,
        "family_id": spatial["family_id"],
        "physical_case_id": spatial["physical_case_id"],
        "label": label,
        "prediction": {
            "formula": "requested_dp_m * (source_sample_mass_kg / prior_candidate_sample_mass_kg)^(1/3)",
            "source_sample_mass_kg": source_mass,
            "prior_candidate_sample_mass_kg": old_mass,
            "prior_candidate_deviation_pct": md["deviation_pct_vs_source"],
            "prior_candidate_dp_m": old_dp,
            "predicted_dp_m": target_dp,
            "source_dp_m": source_dp,
            "actual_mass_gate": "UNKNOWN_UNTIL_GENERATED_XML",
        },
        "source_binding": {
            "generated_xml": record(generated),
            "generated_bi4": record(generated_bi4),
            "gencase_receipt": record(gencase_receipt),
            "solver_receipt": record(solver_receipt),
            "source_definition": record(source_def),
            "relative_dependencies": [
                {"reference": item["reference"], "relative_path": item["relative_path"], "source": item["source"]}
                for item in dependencies
            ],
            "source_producer_vs_current_head": source_head,
        },
        "derived_inputs": {
            "definition": record(definition),
            "relative_dependencies": derived_deps,
        },
        "continuous_vs_intentional": {
            "continuous_geometry_control": "source Def bytes except definition@dp",
            "source_definition_normalized_hash": normalized_geometry_hash(source_def_bytes),
            "derived_definition_normalized_hash": normalized_geometry_hash(derived_bytes),
            "draw_fill_domain_geometry_changed": False,
            "motion_or_acceleration_changed": False,
            "dependencies_byte_identical": all(item["byte_identical"] for item in derived_deps),
            "intentional_changes": ["dp", "h/massfluid/count/lattice phase measured after GenCase"],
        },
        "historical_controls": source_controls(spatial),
        "review_proposals": {
            "baseline_cfl": review.get("baseline_cfl", "UNKNOWN"),
            "half_cfl": review.get("proposed_half_cfl", "UNKNOWN"),
            "dense_cadence_s": review.get("proposed_dense_cadence_s", "UNKNOWN"),
            "status": "proposal_only; no solver control is launched by this request",
        },
        "floating_mass_semantics": spatial.get("generated_mass_semantics", {}).get("floating_mass_semantics", "not floating case"),
        "estimated_storage_bytes": estimated_storage,
        "storage_estimate_policy": "2.5x measured source generated XML+BI4 scaled by (source_dp/predicted_dp)^3 plus copied dependencies/Def/32MiB; GenCase receipt is authoritative",
        "status": "PREPARED_GENCASE_INPUT_NOT_RUN",
        "solver_started": False,
        "full_time_hdf5_read": False,
        "gpu_lease": "none",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    }
    return candidate, {
        "case_dir": case_dir,
        "definition": definition,
        "dependencies": derived_deps,
    }


def input_paths(candidate: dict[str, Any], aux: dict[str, Any]) -> list[Path]:
    source = candidate["source_binding"]
    paths = [
        DISPATCH, STRICT, RUNTIME, Path(__file__).resolve(), GENCASE,
        CURRENT_PATH, REVIEW_PATH, QUALITY_PATH, SPATIAL_MANIFEST_PATH,
        Path(source["generated_xml"]["path"]), Path(source["generated_bi4"]["path"]),
        Path(source["gencase_receipt"]["path"]), Path(source["solver_receipt"]["path"]),
        Path(source["source_definition"]["path"]), aux["definition"],
    ]
    paths.extend(Path(item["derived"]["path"]) for item in aux["dependencies"])
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = path.resolve()
        if str(path) in seen:
            continue
        record(path)
        result.append(path)
        seen.add(str(path))
    return result


def request_for(candidate: dict[str, Any], aux: dict[str, Any], manifest_path: Path, source_head: str) -> dict[str, Any]:
    paths = input_paths(candidate, aux)
    definition = aux["definition"].resolve()
    request = {
        "schema": REQUEST_SCHEMA,
        "family_id": candidate["family_id"],
        "case_id": candidate["case_id"],
        "attempt_id": candidate["case_id"].lower() + "-001",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 2,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": candidate["estimated_storage_bytes"],
        "worktree_root": str(REPO),
        "cwd": str(definition.parent),
        "command": [str(GENCASE), str(definition.with_suffix("")), "{attempt_root}/generated", "-save:all"],
        "input_files": [str(path) for path in paths],
        "input_hashes": {str(path): sha256_file(path) for path in paths},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "ds_data02_stage2_dispatch.py",
            "strict_guard": "ds_data02_strict_dispatch_v1.py",
            "runtime": "ds_data02_runtime_v2.py",
            "launch_commit": source_head,
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "estimated_cpu_core_hours": 2 * 900 / 3600,
            "estimated_new_storage_bytes": candidate["estimated_storage_bytes"],
        },
        "source_binding": candidate["source_binding"],
        "mass_fit_prediction": candidate["prediction"],
        "scope": {
            "sentinel_id": candidate["sentinel_id"],
            "physical_case_id": candidate["physical_case_id"],
            "continuous_geometry_control": candidate["continuous_vs_intentional"],
            "historical_controls": candidate["historical_controls"],
            "gencase_only": True,
            "solver_started": False,
            "full_time_hdf5_read": False,
            "gpu_uuid_lease": "none",
            "mass_gate": "UNKNOWN_UNTIL_GENERATED_XML",
            "scientific_qualification": "UNKNOWN",
        },
        "preparation_manifest": str(manifest_path.resolve()),
        "status": "READY_FOR_PARENT_CPU_GUARD_REVIEW",
    }
    return request


def prepare() -> dict[str, Any]:
    quality, spatial_manifest, review_rows = load_inputs()
    spatial_rows = spatial_by_id(spatial_manifest)
    source_head = git_commit()
    INPUT_ROOT.mkdir(parents=True, exist_ok=False)
    records: list[dict[str, Any]] = []
    for row in hard_rows(quality):
        sid = row["sentinel_id"]
        spatial = spatial_rows[sid]
        review_identity(review_rows, sid, spatial)
        candidate, aux = make_candidate(row, spatial, review_rows, source_head)
        records.append({"candidate": candidate, "aux": {"definition": record(aux["definition"]), "dependencies": aux["dependencies"]}})
    manifest = {
        "schema": SCHEMA,
        "status": "PREPARED_GENCASE_INPUTS_NOT_RUN",
        "generated_at_commit": source_head,
        "quality_source": record(QUALITY_PATH),
        "spatial_source": record(SPATIAL_MANIFEST_PATH),
        "review_source": record(REVIEW_PATH),
        "current_catalog": record(CURRENT_PATH),
        "target_count": len(records),
        "target_policy": "exact F4/F5/F6/F7 quality rows with HARD_FAIL_GT2PCT; one cubic mass-fit prediction per row",
        "gate": "1% target; 2% hard upper bound; actual generated XML mass summed over all fluid blocks",
        "continuous_vs_intentional_rule": "Only definition@dp changes; draw/fill/domain/control and copied motion/STL assets remain byte-identical; h/mass/count/lattice phase are measured outputs",
        "records": records,
        "solver_started": False,
        "full_time_hdf5_read": False,
        "gpu_lease": "none",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    }
    write_json(INPUT_ROOT / "manifest.json", manifest)
    return manifest


def emit_requests(manifest: dict[str, Any]) -> int:
    REQUEST_ROOT.mkdir(parents=True, exist_ok=False)
    manifest_path = INPUT_ROOT / "manifest.json"
    count = 0
    for item in manifest["records"]:
        candidate = item["candidate"]
        aux = {
            "definition": Path(item["aux"]["definition"]["path"]),
            "dependencies": item["aux"]["dependencies"],
        }
        request = request_for(candidate, aux, manifest_path, manifest["generated_at_commit"])
        write_json(REQUEST_ROOT / f"{candidate['case_id'].lower()}.json", request)
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
    count = emit_requests(manifest) if args.emit_requests else 0
    print(json.dumps({"status": "PASS", "targets": manifest["target_count"], "requests": count, "manifest": str(INPUT_ROOT / "manifest.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
