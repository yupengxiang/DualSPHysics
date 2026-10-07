#!/usr/bin/env python3
"""Prepare source-bound GenCase preflights for selected Stage2 sentinels.

This module deliberately has a small, explicit source table.  It resolves the
five CURRENT336 rows by physical identity, verifies the recorded GenCase
receipt and generated XML, and derives isolated inputs by changing only the
``definition@dp`` attribute.  Relative motion/acceleration inputs are copied
byte-for-byte into each isolated input directory.  The resulting requests run
GenCase only; they do not run a solver or read a full-time HDF5 trajectory.

The manifest also registers the full physical time window and the two dense
output plans (same-CFL and half-CFL).  Those plans are metadata for a later
observer-calibrated solver decision.  A successful GenCase run is not a
continuous-geometry, time-discretisation, output, or scientific qualification.
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


SCHEMA = "ds02.stage2.sentinel-spatial-preflight.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CURRENT_PATH = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
REVIEW_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"
QUALITY_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/QUALITY_LABEL_SPLIT_ZH.md"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
INPUT_ROOT = Path(__file__).with_name("stage2_sentinel_spatial_preflight_inputs_v1")
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-sentinel-spatial-preflight-v1"
TARGET_SENTINELS = ("F1-S1", "F1-S2", "F2-S2", "F3-S1", "F3-S2")

# These are the only external paths needed to recover relative inputs for the
# exact CURRENT rows.  They are recorded and hashed in the manifest; no glob or
# "latest" resolution is used.
F3_ACCELERATION_CSV = DATA_ROOT / (
    "families/F3/F3_CELL3_LONG_DP0075_REPAIR1_ADAPTIVE_CFL05_COEF005/"
    "root-cell3-nominal-cfl-decoupled-floor-input-005/prepared/CaseSloshingAccData.csv"
)


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
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def atomic_write(path: Path, payload: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def atomic_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()


def load_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    if not CURRENT_PATH.is_file():
        raise FileNotFoundError(CURRENT_PATH)
    if not REVIEW_PATH.is_file():
        raise FileNotFoundError(REVIEW_PATH)
    current = json.loads(CURRENT_PATH.read_text(encoding="utf-8"))
    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    if current.get("schema") != "ds02.stage2.current336.v1":
        raise ValueError(f"unexpected CURRENT schema: {current.get('schema')}")
    if not isinstance(current.get("cases"), list):
        raise ValueError("CURRENT cases must be a list")
    rows = {row["sentinel_id"]: row for row in review.get("sentinels", [])}
    missing = [sid for sid in TARGET_SENTINELS if sid not in rows]
    if missing:
        raise ValueError(f"missing explicit review rows: {missing}")
    return current, rows


def current_row(current: dict[str, Any], physical_case_id: str) -> dict[str, Any]:
    matches = [row for row in current["cases"] if row.get("physical_case_id") == physical_case_id]
    if len(matches) != 1:
        raise ValueError(f"expected one CURRENT row for {physical_case_id}, found {len(matches)}")
    return matches[0]


def xml_text(path: Path) -> bytes:
    data = path.read_bytes()
    ET.fromstring(data)
    return data


def xml_value(root: ET.Element, tag: str, attribute: str, default: Any = None) -> Any:
    for element in root.iter():
        if element.tag.split("}")[-1].lower() == tag.lower() and attribute in element.attrib:
            return element.attrib[attribute]
    return default


def parameter_value(root: ET.Element, key: str, default: Any = None) -> Any:
    for element in root.iter():
        if element.tag.split("}")[-1].lower() == "parameter" and element.attrib.get("key") == key:
            return element.attrib.get("value", default)
    return default


def float_or_unknown(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalized_geometry_hash(definition: bytes) -> str:
    normalized, count = re.subn(
        rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb'\1<DP>\2', definition, count=1
    )
    if count != 1:
        raise ValueError("source Def must contain exactly one definition@dp marker")
    return hashlib.sha256(normalized).hexdigest()


def candidate_id(sentinel_id: str, label: str, dp: float) -> str:
    safe = sentinel_id.replace("-", "_")
    return f"{safe}_SPATIAL_{label.upper()}_DP{dp:.6f}".replace(".", "p")


def source_def_and_dependencies(
    sentinel_id: str, row: dict[str, Any], all_rows: dict[str, dict[str, Any]],
) -> tuple[Path, list[Path], dict[str, Any]]:
    generated = Path(row["source_bindings"]["generated_xml"]["path"])
    receipt_path = Path(row["source_bindings"]["gencase_receipt"]["path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    sibling_def = generated.with_name(generated.stem + "_Def.xml")
    shared = False
    if not sibling_def.is_file():
        # F3-S2's CURRENT row intentionally points at a nested producer output
        # without a sibling Def.  Its receipt, generated XML bytes, and producer
        # are exactly F3-S1's, so resolve through that explicit identity only.
        if sentinel_id != "F3-S2":
            raise FileNotFoundError(f"no exact generated sibling Def for {sentinel_id}: {sibling_def}")
        peer = all_rows["F3-S1"]
        peer_generated = Path(peer["source_bindings"]["generated_xml"]["path"])
        peer_receipt = Path(peer["source_bindings"]["gencase_receipt"]["path"])
        if row["source_bindings"]["generated_xml"]["sha256"] != peer["source_bindings"]["generated_xml"]["sha256"]:
            raise ValueError("F3-S2 generated XML is not byte-identical to F3-S1")
        if row["source_bindings"]["gencase_receipt"]["sha256"] != peer["source_bindings"]["gencase_receipt"]["sha256"]:
            raise ValueError("F3-S2 GenCase receipt is not byte-identical to F3-S1")
        sibling_def = peer_generated.with_name(peer_generated.stem + "_Def.xml")
        if not sibling_def.is_file() or not peer_receipt.is_file():
            raise FileNotFoundError("F3-S1 shared source Def/receipt is unavailable")
        shared = True

    source_definition = xml_text(sibling_def)
    receipt_hashes = receipt.get("request", {}).get("input_sha256", {})
    source_def_sha = hashlib.sha256(source_definition).hexdigest()
    if source_def_sha not in set(receipt_hashes.values()):
        raise ValueError(f"source Def hash is absent from exact receipt input hashes: {sibling_def}")

    dependencies: list[Path] = []
    if sentinel_id == "F2-S2":
        motion = generated.with_name(generated.stem + "_motion.dat")
        if not motion.is_file():
            raise FileNotFoundError(f"exact F2 motion dependency missing: {motion}")
        dependencies.append(motion)
    elif sentinel_id in {"F3-S1", "F3-S2"}:
        if not F3_ACCELERATION_CSV.is_file():
            raise FileNotFoundError(F3_ACCELERATION_CSV)
        dependencies.append(F3_ACCELERATION_CSV)

    for dependency in dependencies:
        dep_sha = sha256_file(dependency)
        if dep_sha not in set(receipt_hashes.values()):
            raise ValueError(f"dependency hash is absent from exact receipt input hashes: {dependency}")

    return sibling_def, dependencies, {
        "shared_exact_producer": shared,
        "generated_xml": file_record(generated),
        "gencase_receipt": file_record(receipt_path),
        "source_definition": file_record(sibling_def),
        "relative_dependencies": [file_record(path) for path in dependencies],
        "receipt_status": receipt.get("status"),
        "receipt_returncode": receipt.get("returncode"),
        "receipt_attempt_id": receipt.get("request", {}).get("attempt_id"),
        "receipt_input_hash_match": True,
    }


def parse_source_meta(row: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    generated_path = Path(row["source_bindings"]["generated_xml"]["path"])
    generated = xml_text(generated_path)
    root = ET.fromstring(generated)
    raw_root = Path(row["raw_root"]["path"])
    part0 = raw_root / "Part_0000.bi4"
    if not part0.is_file():
        raise FileNotFoundError(part0)
    actual_end = float(row["actual_time_window_s"][1])
    nominal_end = float(review["nominal_tmax_s"])
    if actual_end + 1e-6 < nominal_end:
        raise ValueError(f"CURRENT time window ends before nominal TimeMax for {row['physical_case_id']}")
    cfl = float(xml_value(root, "cflnumber", "value", review["baseline_cfl"]))
    dp = float(xml_value(root, "definition", "dp"))
    h = float(xml_value(root, "h", "value", "nan"))
    massfluid = float(xml_value(root, "massfluid", "value", "nan"))
    tmax = float(parameter_value(root, "TimeMax", nominal_end))
    timeout = float(parameter_value(root, "TimeOut", review["nominal_cadence_s"]))
    particles = int(xml_value(root, "particles", "np", row["particles"]))
    fluid_particles = int(xml_value(root, "fluid", "count", 0))
    return {
        "generated_xml_root": root,
        "generated_xml_meta": {
            "dp_m": dp,
            "h_m": h,
            "massfluid_kg": massfluid,
            "cfl": cfl,
            "time_max_s": tmax,
            "time_out_s": timeout,
            "particles": particles,
            "fluid_particles": fluid_particles,
        },
        "part0": file_record(part0),
        "full_time_window_s": [float(row["actual_time_window_s"][0]), actual_end],
        "nominal_tmax_s": nominal_end,
    }


def output_plan(meta: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    start, end = meta["full_time_window_s"]
    part0_bytes = meta["part0"]["bytes"]
    plans = []
    for cadence in (0.005, 0.002):
        frames = int(math.ceil((end - start) / cadence) + 1)
        native_bytes = part0_bytes * frames
        typed_proxy = native_bytes * 2
        plans.append({
            "cadence_s": cadence,
            "time_window_s": [start, end],
            "planned_frame_count": frames,
            "native_raw_proxy_bytes": native_bytes,
            "typed_proxy_bytes": typed_proxy,
            "reserve20pct_proxy_bytes": int(math.ceil(typed_proxy * 1.2)),
            "proxy_policy": "Part_0000.bi4 bytes × planned full-window frames; typed factor 2 and 20% reserve are planning proxies, not wall/storage guarantees",
            "status": "PLANNED_NO_SOLVER",
        })
    return {
        "full_physical_time_window_s": [start, end],
        "nominal_tmax_s": meta["nominal_tmax_s"],
        "existing_native_cadence_s": review["nominal_cadence_s"],
        "dense_cadence_candidates_s": [0.005, 0.002],
        "same_cfl_and_half_cfl": [
            {
                "dp_m": meta["generated_xml_meta"]["dp_m"],
                "cfl": review["baseline_cfl"],
                "label": "dp0_same_cfl_dense",
                "cadence_s": 0.005,
                "status": "PLANNED_NO_SOLVER",
            },
            {
                "dp_m": meta["generated_xml_meta"]["dp_m"],
                "cfl": review["proposed_half_cfl"],
                "label": "dp0_half_cfl_dense",
                "cadence_s": 0.005,
                "status": "PLANNED_NO_SOLVER",
            },
        ],
        "storage_proxies": plans,
        "observer_calibration_required": True,
        "solver_launch": False,
    }


def derive_candidate(
    sentinel_id: str,
    family: str,
    review: dict[str, Any],
    source_definition: Path,
    dependencies: list[Path],
    source_binding: dict[str, Any],
    meta: dict[str, Any],
    label: str,
    dp: float,
) -> dict[str, Any]:
    case = candidate_id(sentinel_id, label, dp)
    case_dir = INPUT_ROOT / sentinel_id.replace("-", "_") / label
    case_dir.mkdir(parents=True, exist_ok=False)
    source_bytes = source_definition.read_bytes()
    updated, count = re.subn(
        rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)',
        lambda match: match.group(1) + f"{dp:g}".encode("ascii") + match.group(2),
        source_bytes,
        count=1,
    )
    if count != 1:
        raise ValueError(f"source Def must have one definition@dp marker: {source_definition}")
    definition_path = case_dir / f"{case}_Def.xml"
    atomic_write(definition_path, updated)
    dependency_records = []
    for dependency in dependencies:
        destination = case_dir / dependency.name
        if destination.exists():
            raise FileExistsError(destination)
        shutil.copyfile(dependency, destination)
        dependency_records.append({
            "source": file_record(dependency),
            "derived": file_record(destination),
            "relative_name": dependency.name,
            "byte_identical": sha256_file(dependency) == sha256_file(destination),
        })

    ratio = meta["generated_xml_meta"]["dp_m"] / dp
    estimated_particles = int(math.ceil(meta["generated_xml_meta"]["particles"] * ratio**3))
    estimated_storage = max(16 * 1024 * 1024, int(math.ceil(meta["part0"]["bytes"] * ratio**3 * 2.0)))
    return {
        "case_id": case,
        "sentinel_id": sentinel_id,
        "family_id": family,
        "physical_case_id": review["source_physical_case_id"],
        "label": label,
        "dp_m": dp,
        "source_dp_m": meta["generated_xml_meta"]["dp_m"],
        "intentional_resolution_variation": {
            "dp_m": dp,
            "h_m": "UNKNOWN_UNTIL_GENERATED_XML",
            "massfluid_kg": "UNKNOWN_UNTIL_GENERATED_XML",
            "particle_count": "UNKNOWN_UNTIL_GENERATED_XML",
            "lattice_phase": "same source origin policy; exact phase/count remains UNKNOWN until generated XML",
        },
        "continuous_geometry_control": {
            "source_definition_normalized_hash": normalized_geometry_hash(source_bytes),
            "derived_definition_normalized_hash": normalized_geometry_hash(updated),
            "draw_fill_geometry_changed": False,
            "motion_or_acceleration_changed": False,
            "relative_dependencies_byte_identical": all(item["byte_identical"] for item in dependency_records),
            "stl_dependency": "NONE_DECLARED_IN_EXACT_DEF",
            "strict_continuous_equivalence": "PRECHECKED_INPUT_COPY_ONLY; not a solver qualification",
        },
        "source_binding": source_binding,
        "derived_inputs": {
            "definition": file_record(definition_path),
            "relative_dependencies": dependency_records,
        },
        "estimated_particle_count": estimated_particles,
        "estimated_storage_bytes": estimated_storage,
        "estimate_policy": "source Part_0000 bytes × (source dp / candidate dp)^3 × 2; GenCase receipt controls actual output",
    }


def prepare() -> dict[str, Any]:
    current, reviews = load_inputs()
    INPUT_ROOT.mkdir(parents=True, exist_ok=False)
    sentinel_records = []
    for sentinel_id in TARGET_SENTINELS:
        review = reviews[sentinel_id]
        row = current_row(current, review["source_physical_case_id"])
        source_definition, dependencies, binding = source_def_and_dependencies(sentinel_id, row, {
            sid: current_row(current, reviews[sid]["source_physical_case_id"]) for sid in TARGET_SENTINELS
        })
        generated_meta = parse_source_meta(row, review)
        plans = output_plan(generated_meta, review)
        spacings = [float(value) for value in review["proposed_spacing_m"]]
        labels = ("coarse", "original", "fine")
        candidates = [
            derive_candidate(
                sentinel_id, review["family"], review, source_definition, dependencies,
                binding, generated_meta, label, dp
            )
            for label, dp in zip(labels, spacings)
        ]
        sentinel_records.append({
            "sentinel_id": sentinel_id,
            "family_id": review["family"],
            "physical_case_id": review["source_physical_case_id"],
            "current_row": {
                "family_id": row["family_id"],
                "physical_case_id": row["physical_case_id"],
                "runtime_case_alias": row["runtime_case_alias"],
                "frames": row["frames"],
                "particles": row["particles"],
                "actual_time_window_s": row["actual_time_window_s"],
                "trajectory_producer_sha256": row["trajectory"]["producer_declared_sha256"],
                "trajectory_mtime_ns": row["trajectory"]["mtime_ns"],
                "raw_root": row["raw_root"],
            },
            "source_binding": binding,
            "generated_xml_meta": generated_meta["generated_xml_meta"],
            "preflight_scope": {
                "three_spatial_grid": spacings,
                "same_cfl": review["baseline_cfl"],
                "half_cfl": review["proposed_half_cfl"],
                "full_time_window_s": plans["full_physical_time_window_s"],
                "domain_or_geometry_error": "input-copy checks only; solver/domain qualification UNKNOWN",
                "time_error": "UNKNOWN until observer-calibrated full-window solver comparison",
                "output_error": "UNKNOWN until dense cadence comparison over full window",
                "task_error": "UNKNOWN until physical observation task is evaluated",
            },
            "time_output_plan": plans,
            "candidates": candidates,
            "status": "PREPARED_GENCASЕ_INPUTS_NOT_RUN".replace("Е", "E"),
            "solver_started": False,
            "full_time_hdf5_read": False,
            "observer_calibration": "NOT_RUN",
            "QI": "NOT_ASSESSED",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        })
    manifest = {
        "schema": SCHEMA,
        "status": "PREPARED_GENCASE_INPUTS_NOT_RUN",
        "source_resolution_policy": "fixed CURRENT336 physical identities and exact receipt/generated XML paths; no latest glob or family fallback",
        "current_catalog": file_record(CURRENT_PATH),
        "review_matrix": file_record(REVIEW_PATH),
        "quality_label_split": file_record(QUALITY_PATH),
        "target_sentinels": list(TARGET_SENTINELS),
        "error_budget_registration": {
            "position_macro_fraction_of_L": 0.02,
            "position_event_fraction_of_L": 0.05,
            "velocity_or_kinetic_energy_fraction_of_nonzero_scale": 0.05,
            "region_mass_fraction": 0.03,
            "event_time_fraction": 0.01,
            "time_and_output_each_fraction_of_total_gate": 0.25,
            "source": str(QUALITY_PATH),
            "status": "PRE_REGISTERED_FOR_CONSUMER_CALIBRATION; no result-time relaxation",
        },
        "continuous_vs_intentional_rule": "Def draw/fill/domain/control and relative dependencies are copied byte-identically; dp/h/mass/count/lattice phase vary intentionally and remain measured outputs",
        "sentinels": sentinel_records,
        "solver_started": False,
        "gpu_lease": "none",
        "full_time_hdf5_read": False,
    }
    atomic_json(INPUT_ROOT / "manifest.json", manifest)
    return manifest


def request_for(candidate: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    definition = Path(candidate["derived_inputs"]["definition"]["path"]).resolve()
    sentinel = candidate["sentinel_id"]
    source_binding = candidate["source_binding"]
    inputs = [
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py",
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        Path(__file__).resolve(),
        GENCASE.resolve(),
        CURRENT_PATH,
        REVIEW_PATH,
        QUALITY_PATH,
        manifest_path,
        Path(source_binding["generated_xml"]["path"]),
        Path(source_binding["gencase_receipt"]["path"]),
        Path(source_binding["source_definition"]["path"]),
        definition,
    ]
    inputs.extend(Path(item["derived"]["path"]) for item in candidate["derived_inputs"]["relative_dependencies"])
    # Preserve order while rejecting accidental duplicate paths.
    unique_inputs = []
    seen = set()
    for path in inputs:
        path = path.resolve()
        if str(path) not in seen:
            unique_inputs.append(path)
            seen.add(str(path))
    for path in unique_inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
    request_path = REQUEST_DIR / f"{candidate['case_id'].lower()}.json"
    return {
        "schema": REQUEST_SCHEMA,
        "family_id": candidate["family_id"],
        "case_id": candidate["case_id"],
        "attempt_id": candidate["case_id"].lower() + "-001",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 2,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": candidate["estimated_storage_bytes"],
        "worktree_root": str(REPO),
        "cwd": str(definition.parent),
        "command": [str(GENCASE), str(definition.with_suffix("")), "{attempt_root}/generated", "-save:all"],
        "input_files": [str(path) for path in unique_inputs],
        "input_hashes": {str(path): sha256_file(path) for path in unique_inputs},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "ds_data02_stage2_dispatch.py",
            "strict_guard": "ds_data02_strict_dispatch_v1.py",
            "runtime": "ds_data02_runtime_v2.py",
            "launch_commit": git_commit(),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "estimated_cpu_core_hours": 2 * 300 / 3600,
            "estimated_new_storage_bytes": candidate["estimated_storage_bytes"],
        },
        "scope": {
            "sentinel_id": sentinel,
            "physical_case_id": candidate["physical_case_id"],
            "continuous_source_identity": source_binding,
            "three_spatial_grid_label": candidate["label"],
            "dp_m": candidate["dp_m"],
            "intentional_resolution_variation": candidate["intentional_resolution_variation"],
            "time_output_plan": "manifest full physical window; same-CFL and half-CFL dense are planned metadata",
            "gencase_only": True,
            "solver_started": False,
            "full_time_hdf5_read": False,
            "gpu_uuid_lease": "none",
            "scientific_qualification": "UNKNOWN",
        },
    }


def emit_requests(manifest: dict[str, Any], output_dir: Path) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = (INPUT_ROOT / "manifest.json").resolve()
    requests = []
    for sentinel in manifest["sentinels"]:
        for candidate in sentinel["candidates"]:
            request = request_for(candidate, manifest_path)
            atomic_json(output_dir / f"{candidate['case_id'].lower()}.json", request)
            requests.append(request)
    return requests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--emit-requests-dir", type=Path)
    args = parser.parse_args()
    if not args.prepare and args.emit_requests_dir is None:
        raise SystemExit("choose --prepare and/or --emit-requests-dir")
    if args.prepare:
        manifest = prepare()
    else:
        manifest = json.loads((INPUT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    if args.emit_requests_dir is None:
        print(json.dumps({"status": "PASS", "manifest": str(INPUT_ROOT / "manifest.json"), "candidates": 15}, ensure_ascii=False))
        return 0
    requests = emit_requests(manifest, args.emit_requests_dir)
    print(json.dumps({"status": "PASS", "requests": len(requests), "output_dir": str(args.emit_requests_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
