#!/usr/bin/env python3
"""Prepare source-bound, GenCase-only spatial preflights for F4--F7.

This is a forward-only preparation artifact.  It reads the exact CURRENT336
rows and their recorded GenCase/solver receipts, verifies the source identity
tuple, and derives three isolated inputs by changing only ``definition@dp``.
It never starts a solver, reads a full-time HDF5 trajectory, or treats a
historical solver receipt as a new qualification.  The historical solver
argv/XML controls and the review dense-output proposal are recorded
separately, including conflicts such as an XML TimeMax overridden by a solver
``-tmax`` flag.

The source generated ``.bi4`` size plus the exact copied dependencies is used
for a conservative GenCase storage reservation.  This is deliberately larger
than the old 16 MiB default so a short process cannot evade the reservation
check.  A successful GenCase request remains only a spatial-input preflight;
continuous geometry, time integration, output cadence, and scientific
qualification stay UNKNOWN until an independently registered observer task.
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


SCHEMA = "ds02.stage2.remaining-sentinel-spatial-preflight.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CURRENT_PATH = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
REVIEW_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"
QUALITY_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/QUALITY_LABEL_SPLIT_ZH.md"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
INPUT_ROOT = Path(__file__).with_name("stage2_remaining_sentinel_spatial_preflight_inputs_v1")
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-remaining-sentinel-spatial-preflight-v1"
TARGET_SENTINELS = ("F4-S1", "F4-S2", "F5-S1", "F5-S2", "F6-S1", "F6-S2", "F7-S1", "F7-S2")
LABELS = ("coarse", "original", "fine")
MiB = 1024 * 1024


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


def tag(element: ET.Element) -> str:
    return element.tag.split("}")[-1].lower()


def parse_xml(path: Path) -> tuple[bytes, ET.Element]:
    data = path.read_bytes()
    return data, ET.fromstring(data)


def unique_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def value_or_unknown(values: list[str]) -> str:
    values = unique_values(values)
    return values[0] if len(values) == 1 else ("UNKNOWN" if not values else "UNKNOWN_CONFLICT")


def numeric_or_unknown(values: list[str]) -> str:
    values = unique_values(values)
    if not values:
        return "UNKNOWN"
    try:
        numbers = [float(value) for value in values]
    except (TypeError, ValueError):
        return values[0] if len(values) == 1 else "UNKNOWN_CONFLICT"
    if max(numbers) - min(numbers) > 1e-12:
        return "UNKNOWN_CONFLICT"
    return format(numbers[0], ".15g")


def values(root: ET.Element, element_tag: str, attribute: str) -> list[str]:
    return [
        element.attrib[attribute]
        for element in root.iter()
        if tag(element) == element_tag and attribute in element.attrib
    ]


def parameter_values(root: ET.Element, key: str) -> list[str]:
    return [
        element.attrib["value"]
        for element in root.iter()
        if tag(element) == "parameter" and element.attrib.get("key") == key and "value" in element.attrib
    ]


def cli_values(command: list[str], prefix: str) -> list[str]:
    return [arg.split(":", 1)[1] for arg in command if arg.startswith(prefix + ":")]


def numeric(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalized_geometry_hash(data: bytes) -> str:
    normalized, count = re.subn(
        rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb'\1<DP>\2', data, count=1
    )
    if count != 1:
        raise ValueError("expected exactly one definition@dp attribute")
    return hashlib.sha256(normalized).hexdigest()


def candidate_id(sentinel_id: str, label: str, dp: float) -> str:
    return f"{sentinel_id.replace('-', '_')}_SPATIAL_V1_{label.upper()}_DP{dp:.6f}".replace(".", "p")


def request_hashes(request: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in request.get("input_sha256", {}).items():
        result[str(Path(name).resolve())] = value
    for name, value in request.get("input_hashes", {}).items():
        key = str(Path(name).resolve())
        if key in result and result[key] != value:
            raise ValueError(f"conflicting source request hash for {key}")
        result[key] = value
    return result


def load_catalog() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    current = json.loads(CURRENT_PATH.read_text(encoding="utf-8"))
    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    if current.get("schema") != "ds02.stage2.current336.v1":
        raise ValueError(f"unexpected CURRENT schema: {current.get('schema')}")
    rows = {row["sentinel_id"]: row for row in review.get("sentinels", [])}
    missing = [sid for sid in TARGET_SENTINELS if sid not in rows]
    if missing:
        raise ValueError(f"missing exact review rows: {missing}")
    return current, rows


def current_row(current: dict[str, Any], physical_case_id: str) -> dict[str, Any]:
    matches = [row for row in current.get("cases", []) if row.get("physical_case_id") == physical_case_id]
    if len(matches) != 1:
        raise ValueError(f"expected one exact CURRENT row for {physical_case_id}, found {len(matches)}")
    return matches[0]


def verify_catalog_binding(row: dict[str, Any], key: str) -> tuple[Path, dict[str, Any]]:
    binding = row.get("source_bindings", {}).get(key)
    if not isinstance(binding, dict) or not binding.get("path") or not binding.get("sha256"):
        raise ValueError(f"CURRENT source binding is incomplete: {row.get('physical_case_id')}:{key}")
    path = Path(binding["path"]).resolve()
    record = file_record(path)
    if record["sha256"] != binding["sha256"]:
        raise ValueError(f"CURRENT source binding digest mismatch: {path}")
    return path, record


def receipt_for(row: dict[str, Any], key: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path, record = verify_catalog_binding(row, key)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    request = receipt.get("request", {})
    if not isinstance(request, dict):
        raise ValueError(f"receipt request is not an object: {path}")
    return path, receipt, request


def source_input_path(request: dict[str, Any], expected_sha: str, suffix: str) -> Path:
    matches = []
    hashes = request_hashes(request)
    for raw in request.get("input_files", []):
        path = Path(raw).resolve()
        if path.is_file() and path.name.endswith(suffix) and hashes.get(str(path)) == expected_sha:
            matches.append(path)
    if len(matches) != 1:
        raise ValueError(f"expected one exact {suffix} input with hash {expected_sha}, found {matches}")
    return matches[0]


def resolve_source_definition(
    generated: Path, gencase_request: dict[str, Any], solver_request: dict[str, Any]
) -> tuple[Path, dict[str, Any]]:
    g_hashes = request_hashes(gencase_request)
    s_hashes = request_hashes(solver_request)
    preferred_name = generated.stem + "_Def.xml"
    candidates: list[Path] = []
    for raw in gencase_request.get("input_files", []):
        path = Path(raw).resolve()
        if path.is_file() and path.name == preferred_name:
            if g_hashes.get(str(path)) == sha256_file(path):
                candidates.append(path)
    # A few historical producers put the Def outside the generated directory;
    # use only the exact input path from the recorded request, never a glob.
    if not candidates:
        # Some source producers add a case-specific suffix to the Def name
        # (for example F5 M095_T090), while the exact GenCase request still
        # contains only one Def input.  Select that one exact request input;
        # do not search the filesystem.
        for raw in gencase_request.get("input_files", []):
            path = Path(raw).resolve()
            if path.is_file() and path.name.endswith("_Def.xml") and g_hashes.get(str(path)) == sha256_file(path):
                candidates.append(path)
    if not candidates:
        for raw in solver_request.get("input_files", []):
            path = Path(raw).resolve()
            if path.is_file() and path.name.endswith("_Def.xml") and s_hashes.get(str(path)) == sha256_file(path):
                candidates.append(path)
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) != 1:
        raise ValueError(f"cannot resolve exact source Def for {generated}: {candidates}")
    source = candidates[0]
    source_sha = sha256_file(source)
    if source_sha not in set(g_hashes.values()):
        raise ValueError(f"source Def is not present in the exact GenCase request hash set: {source}")
    return source, {
        "record": file_record(source),
        "gencase_request_hash_match": True,
        "solver_request_hash_match": source_sha in set(s_hashes.values()),
        "selection": "exact generated-stem Def from recorded GenCase/solver input lists",
    }


def referenced_file_names(*roots: ET.Element) -> list[str]:
    refs: list[str] = []
    for root in roots:
        for element in root.iter():
            for key, value in element.attrib.items():
                lower = value.lower()
                if key.lower() in {"file", "name", "value"} and lower.endswith((".csv", ".dat", ".stl")):
                    refs.append(value)
    # Keep order and exact spelling; duplicate XML refs are harmless.
    return list(dict.fromkeys(refs))


def resolve_dependencies(
    refs: list[str], gencase_request: dict[str, Any], solver_request: dict[str, Any]
) -> list[dict[str, Any]]:
    g_hashes = request_hashes(gencase_request)
    s_hashes = request_hashes(solver_request)
    deps: list[dict[str, Any]] = []
    for ref in refs:
        relative = Path(ref)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe relative dependency reference: {ref}")
        matches = []
        for raw in gencase_request.get("input_files", []):
            path = Path(raw).resolve()
            if not path.is_file() or path.name != relative.name:
                continue
            digest = g_hashes.get(str(path))
            # The GenCase and solver receipts may copy the same asset into
            # different producer directories.  Match the immutable digest,
            # not the historical pathname.
            if digest and digest == sha256_file(path) and digest in set(s_hashes.values()):
                matches.append(path)
        matches = list(dict.fromkeys(matches))
        if len(matches) != 1:
            raise ValueError(f"cannot resolve exact dependency {ref}: {matches}")
        source = matches[0]
        deps.append({
            "reference": ref,
            "relative_path": relative.as_posix(),
            "source": file_record(source),
            "gencase_request_hash_match": True,
            "solver_request_hash_match": True,
        })
    return deps


def fluid_and_floating_summary(root: ET.Element) -> dict[str, Any]:
    fluid_blocks = []
    floating_blocks = []
    for element in root.iter():
        if tag(element) == "fluid" and "mkfluid" in element.attrib and "count" in element.attrib:
            try:
                count: int | str = int(element.attrib["count"])
            except ValueError:
                count = "UNKNOWN"
            fluid_blocks.append({"mkfluid": element.attrib.get("mkfluid", "UNKNOWN"), "count": count})
        if tag(element) == "floating" and "count" in element.attrib:
            try:
                count = int(element.attrib["count"])
            except ValueError:
                count = "UNKNOWN"
            floating_blocks.append({"mkbound": element.attrib.get("mkbound", "UNKNOWN"), "count": count})
    mass_values = values(root, "massfluid", "value")
    result: dict[str, Any] = {
        "fluid_blocks": fluid_blocks,
        "floating_blocks": floating_blocks,
        "massfluid_values": mass_values,
    }
    try:
        counts = [int(item["count"]) for item in fluid_blocks]
        mass = float(numeric_or_unknown(mass_values))
        result["total_fluid_particles"] = sum(counts)
        result["sample_mass_kg"] = sum(counts) * mass
    except (TypeError, ValueError):
        result["sample_mass_kg"] = "UNKNOWN"
        result["sample_mass_reason"] = "sum of mkfluid blocks or common massfluid unavailable"
    massbody = numeric_or_unknown(values(root, "massbody", "value"))
    inertia = {axis: numeric_or_unknown(values(root, "inertia", axis)) for axis in ("x", "y", "z")}
    result["rigid_body_massbody_kg"] = massbody
    result["rigid_body_inertia"] = inertia
    result["floating_particle_masspart_kg"] = numeric_or_unknown(
        [element.attrib[key] for element in root.iter() for key in ("masspart", "MassBound") if key in element.attrib]
        + values(root, "masspart", "value")
    )
    result["floating_sample_mass_kg"] = "UNKNOWN"
    result["floating_mass_semantics"] = (
        "particle sample mass requires a floating masspart from native/typed state; "
        "massbody is the rigid physical mass and must not be replaced by a floating particle sum"
    )
    return result


def exact_source_controls(
    sid: str,
    row: dict[str, Any],
    review: dict[str, Any],
    generated_path: Path,
    generated_root: ET.Element,
    solver_receipt_path: Path,
    solver_receipt: dict[str, Any],
    source_def: Path,
    source_dependencies: list[dict[str, Any]],
) -> dict[str, Any]:
    command = solver_receipt.get("request", {}).get("command", [])
    if not isinstance(command, list):
        command = []
    xml_controls = {
        "cflnumber": numeric_or_unknown(values(generated_root, "cflnumber", "value")),
        "dp_m": numeric_or_unknown(values(generated_root, "definition", "dp")),
        "h_m": numeric_or_unknown(values(generated_root, "h", "value")),
        "DtIni": numeric_or_unknown(parameter_values(generated_root, "DtIni")),
        "DtMin": numeric_or_unknown(parameter_values(generated_root, "DtMin")),
        "DtFixed": numeric_or_unknown(parameter_values(generated_root, "DtFixed")),
        "CoefDtMin": numeric_or_unknown(parameter_values(generated_root, "CoefDtMin")),
        "TimeMax": numeric_or_unknown(parameter_values(generated_root, "TimeMax")),
        "TimeOut": numeric_or_unknown(parameter_values(generated_root, "TimeOut")),
    }
    cli_tmax = numeric_or_unknown(cli_values(command, "-tmax"))
    cli_tout = numeric_or_unknown(cli_values(command, "-tout"))
    xml_tmax = numeric(xml_controls["TimeMax"])
    cli_tmax_num = numeric(cli_tmax)
    xml_tout = numeric(xml_controls["TimeOut"])
    cli_tout_num = numeric(cli_tout)
    if xml_tmax is None or cli_tmax_num is None:
        tmax_status = "UNKNOWN"
    elif abs(xml_tmax - cli_tmax_num) <= 1e-12:
        tmax_status = "MATCH"
    else:
        tmax_status = "CLI_OVERRIDES_XML"
    if xml_tout is None or cli_tout_num is None:
        tout_status = "UNKNOWN"
    elif abs(xml_tout - cli_tout_num) <= 1e-12:
        tout_status = "MATCH"
    else:
        tout_status = "CLI_OVERRIDES_XML"
    solver_hashes = request_hashes(solver_receipt.get("request", {}))
    dep_hashes = [item["source"]["sha256"] for item in source_dependencies]
    source_def_sha = sha256_file(source_def)
    # The selected Def is recorded separately by prepare(); all dependency
    # hashes are checked against the exact solver input list here.
    dependency_binding_ok = set(dep_hashes).issubset(set(solver_hashes.values()))
    source_def_binding_ok = source_def_sha in set(solver_hashes.values())
    generated_binding_ok = sha256_file(generated_path) in set(solver_hashes.values())
    binding_status = "MATCH" if dependency_binding_ok and (source_def_binding_ok or generated_binding_ok) else "UNKNOWN"
    return {
        "sentinel_id": sid,
        "family_id": row["family_id"],
        "physical_case_id": row["physical_case_id"],
        "historical_solver_receipt": file_record(solver_receipt_path),
        "historical_solver_status": solver_receipt.get("status"),
        "historical_solver_returncode": solver_receipt.get("returncode"),
        "historical_solver_command": command,
        "historical_solver_input_hash_binding": binding_status,
        "source_def_in_solver_request": source_def_binding_ok,
        "generated_xml_in_solver_request": generated_binding_ok,
        "exact_generated_xml": file_record(generated_path),
        "xml_controls": xml_controls,
        "solver_argv_controls": {
            "tmax_s": cli_tmax,
            "tout_s": cli_tout,
            "other_flags": [arg for arg in command if isinstance(arg, str) and arg.startswith("-") and not arg.startswith(("-tmax:", "-tout:"))],
        },
        "effective_time_controls": {
            "time_max_s": cli_tmax,
            "output_cadence_s": cli_tout,
            "time_max_resolution": tmax_status,
            "output_cadence_resolution": tout_status,
            "dt_actual_or_clamp": "UNKNOWN_UNTIL_SOLVER_RUNTIME_RECEIPT",
        },
        "review_proposals_only": {
            "baseline_cfl": review.get("baseline_cfl", "UNKNOWN"),
            "proposed_half_cfl": review.get("proposed_half_cfl", "UNKNOWN"),
            "proposed_dense_cadence_s": review.get("proposed_dense_cadence_s", "UNKNOWN"),
            "status": "proposal_only; never substituted for exact historical solver argv/XML",
        },
        "status": "PASS_HISTORICAL_SOURCE_CONTROLS" if solver_receipt.get("status") == "completed" and binding_status == "MATCH" else "UNKNOWN_SOURCE_CONTROLS",
    }


def source_meta(
    sid: str,
    row: dict[str, Any],
    review: dict[str, Any],
    generated_path: Path,
    generated_root: ET.Element,
    gencase_receipt_path: Path,
    gencase_receipt: dict[str, Any],
    solver_receipt_path: Path,
    solver_receipt: dict[str, Any],
    source_def: Path,
    dependencies: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_root = Path(row["raw_root"]["path"])
    part0 = raw_root / "Part_0000.bi4"
    if not part0.is_file():
        raise FileNotFoundError(part0)
    generated_bi4 = generated_path.with_suffix(".bi4")
    if not generated_bi4.is_file():
        raise FileNotFoundError(generated_bi4)
    start, end = [float(value) for value in row["actual_time_window_s"]]
    nominal_tmax = float(review["nominal_tmax_s"])
    if end + 1e-6 < nominal_tmax:
        raise ValueError(f"CURRENT window ends before review nominal TimeMax: {sid}")
    xml_controls = {
        "dp_m": numeric_or_unknown(values(generated_root, "definition", "dp")),
        "h_m": numeric_or_unknown(values(generated_root, "h", "value")),
        "cflnumber": numeric_or_unknown(values(generated_root, "cflnumber", "value")),
        "particles": value_or_unknown(values(generated_root, "particles", "np")),
    }
    generated_mass = fluid_and_floating_summary(generated_root)
    command = solver_receipt.get("request", {}).get("command", [])
    cli_tmax = numeric_or_unknown(cli_values(command, "-tmax"))
    cli_tout = numeric_or_unknown(cli_values(command, "-tout"))
    source_binding = {
        "generated_xml": file_record(generated_path),
        "generated_bi4": file_record(generated_bi4),
        "gencase_receipt": file_record(gencase_receipt_path),
        "solver_receipt": file_record(solver_receipt_path),
        "source_definition": file_record(source_def),
        "relative_dependencies": dependencies,
        "gencase_status": gencase_receipt.get("status"),
        "gencase_returncode": gencase_receipt.get("returncode"),
        "solver_status": solver_receipt.get("status"),
        "solver_returncode": solver_receipt.get("returncode"),
        "actual_solver_tmax_s": cli_tmax,
        "actual_solver_tout_s": cli_tout,
        "source_producer_vs_current_head": {
            "historical_gencase_receipt": file_record(gencase_receipt_path),
            "historical_solver_receipt": file_record(solver_receipt_path),
            "preparation_current_head": git_commit(),
            "interpretation": "historical producer/solver evidence; this branch does not claim to reproduce it",
        },
    }
    return {
        "generated_xml_meta": xml_controls,
        "generated_mass_semantics": generated_mass,
        "source_binding": source_binding,
        "source_def_normalized_hash": normalized_geometry_hash(source_def.read_bytes()),
        "part0": file_record(part0),
        "full_time_window_s": [start, end],
        "review_nominal_tmax_s": nominal_tmax,
        "historical_solver_controls": exact_source_controls(
            sid, row, review, generated_path, generated_root, solver_receipt_path,
            solver_receipt, source_def, dependencies,
        ),
    }


def output_plan(meta: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    start, end = meta["full_time_window_s"]
    proposed = review.get("proposed_dense_cadence_s", "UNKNOWN")
    cadence = numeric(proposed)
    frames = "UNKNOWN" if cadence is None or cadence <= 0 else int(math.ceil((end - start) / cadence) + 1)
    raw_bytes = meta["part0"]["bytes"]
    native_proxy = "UNKNOWN" if frames == "UNKNOWN" else raw_bytes * frames
    typed_proxy = "UNKNOWN" if native_proxy == "UNKNOWN" else native_proxy * 2
    reserve_proxy = "UNKNOWN" if typed_proxy == "UNKNOWN" else int(math.ceil(typed_proxy * 1.2))
    return {
        "full_physical_time_window_s": [start, end],
        "historical_solver_time_max_s": meta["historical_solver_controls"]["effective_time_controls"]["time_max_s"],
        "historical_solver_output_cadence_s": meta["historical_solver_controls"]["effective_time_controls"]["output_cadence_s"],
        "review_dense_cadence_s": proposed,
        "planned_frame_count": frames,
        "native_raw_proxy_bytes": native_proxy,
        "typed_proxy_bytes": typed_proxy,
        "reserve20pct_proxy_bytes": reserve_proxy,
        "same_cfl_dp0": {
            "cfl": meta["historical_solver_controls"]["xml_controls"]["cflnumber"],
            "cadence_s": proposed,
            "status": "PLANNED_NO_SOLVER",
        },
        "half_cfl_dp0": {
            "cfl": review.get("proposed_half_cfl", "UNKNOWN"),
            "cadence_s": proposed,
            "status": "PLANNED_NO_SOLVER; effective dt/clamp UNKNOWN",
        },
        "proxy_policy": "Part_0000.bi4 bytes x full-window frames; typed factor 2 and 20% are planning proxies, not storage guarantees",
        "solver_launch": False,
        "full_time_hdf5_read": False,
    }


def derive_candidate(
    sid: str,
    review: dict[str, Any],
    source_def: Path,
    dependencies: list[dict[str, Any]],
    meta: dict[str, Any],
    label: str,
    dp: float,
) -> dict[str, Any]:
    case = candidate_id(sid, label, dp)
    case_dir = INPUT_ROOT / sid.replace("-", "_") / label
    case_dir.mkdir(parents=True, exist_ok=False)
    source_bytes = source_def.read_bytes()
    updated, count = re.subn(
        rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)',
        lambda match: match.group(1) + f"{dp:g}".encode("ascii") + match.group(2),
        source_bytes,
        count=1,
    )
    if count != 1:
        raise ValueError(f"source Def has no unique definition@dp: {source_def}")
    definition = case_dir / f"{case}_Def.xml"
    atomic_write(definition, updated)
    derived_dependencies = []
    seen_destinations: set[str] = set()
    for item in dependencies:
        relative = Path(item["relative_path"])
        destination = case_dir / relative
        key = str(destination.resolve())
        if key in seen_destinations:
            continue
        seen_destinations.add(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(destination)
        shutil.copyfile(item["source"]["path"], destination)
        derived_dependencies.append({
            "reference": item["reference"],
            "relative_path": relative.as_posix(),
            "source": item["source"],
            "derived": file_record(destination),
            "byte_identical": item["source"]["sha256"] == sha256_file(destination),
        })
    source_dp = numeric(meta["generated_xml_meta"]["dp_m"])
    if source_dp is None or dp <= 0:
        raise ValueError(f"invalid source/candidate dp for {case}")
    ratio = source_dp / dp
    particles = numeric(meta["generated_xml_meta"]["particles"])
    source_output_bytes = meta["source_binding"]["generated_bi4"]["bytes"] + meta["source_binding"]["generated_xml"]["bytes"]
    dependency_bytes = sum(item["source"]["bytes"] for item in dependencies)
    base_bytes = source_output_bytes * ratio**3 + dependency_bytes + len(updated) + 32 * MiB
    estimated_storage = int(math.ceil(base_bytes * 2.5 / MiB) * MiB)
    return {
        "case_id": case,
        "sentinel_id": sid,
        "family_id": review["family"],
        "physical_case_id": review["source_physical_case_id"],
        "label": label,
        "dp_m": dp,
        "source_dp_m": source_dp,
        "intentional_resolution_variation": {
            "dp_m": dp,
            "h_m": "UNKNOWN_UNTIL_GENERATED_XML",
            "massfluid_kg": "UNKNOWN_UNTIL_GENERATED_XML",
            "particle_count": "UNKNOWN_UNTIL_GENERATED_XML",
            "lattice_phase": "same source Def origin policy; generated phase/count must be measured",
        },
        "continuous_geometry_control": {
            "source_definition_normalized_hash": normalized_geometry_hash(source_bytes),
            "derived_definition_normalized_hash": normalized_geometry_hash(updated),
            "draw_fill_geometry_changed": False,
            "motion_or_acceleration_changed": False,
            "relative_dependencies_byte_identical": all(item["byte_identical"] for item in derived_dependencies),
            "stl_dependency": "PRESENT_AND_COPIED" if any(Path(item["relative_path"]).suffix.lower() == ".stl" for item in dependencies) else "NONE_DECLARED_IN_EXACT_SOURCE",
            "strict_continuous_equivalence": "PRECHECKED_INPUT_COPY_ONLY; solver/domain qualification UNKNOWN",
        },
        "source_binding": meta["source_binding"],
        "derived_inputs": {
            "definition": file_record(definition),
            "relative_dependencies": derived_dependencies,
        },
        "estimated_particle_count": "UNKNOWN" if particles is None else int(math.ceil(particles * ratio**3)),
        "estimated_storage_bytes": estimated_storage,
        "estimate_policy": "2.5x[(exact source generated bi4+xml bytes)x(dp0/dp)^3 + copied dependency bytes + Def bytes + 32MiB]; actual guard receipt is authoritative",
    }


def prepare() -> dict[str, Any]:
    current, reviews = load_catalog()
    INPUT_ROOT.mkdir(parents=True, exist_ok=False)
    records = []
    all_rows = {}
    for sid in TARGET_SENTINELS:
        review = reviews[sid]
        row = current_row(current, review["source_physical_case_id"])
        if row.get("family_id") != review.get("family"):
            raise ValueError(f"family identity mismatch for {sid}")
        if row.get("physical_case_id") != review.get("source_physical_case_id"):
            raise ValueError(f"physical identity mismatch for {sid}")
        all_rows[sid] = row
    for sid in TARGET_SENTINELS:
        review = reviews[sid]
        row = all_rows[sid]
        generated_path, generated_record = verify_catalog_binding(row, "generated_xml")
        gencase_path, gencase_receipt, gencase_request = receipt_for(row, "gencase_receipt")
        solver_path, solver_receipt, solver_request = receipt_for(row, "solver_receipt")
        if gencase_receipt.get("status") != "completed" or gencase_receipt.get("returncode") != 0:
            raise ValueError(f"historical GenCase receipt is not successful for {sid}")
        if solver_receipt.get("status") != "completed" or solver_receipt.get("returncode") != 0:
            raise ValueError(f"historical solver receipt is not successful for {sid}")
        generated_bytes, generated_root = parse_xml(generated_path)
        source_def, source_def_record = resolve_source_definition(generated_path, gencase_request, solver_request)
        refs = referenced_file_names(generated_root, ET.fromstring(source_def.read_bytes()))
        dependencies = resolve_dependencies(refs, gencase_request, solver_request)
        meta = source_meta(
            sid, row, review, generated_path, generated_root, gencase_path, gencase_receipt,
            solver_path, solver_receipt, source_def, dependencies,
        )
        meta["source_binding"]["source_definition_resolution"] = source_def_record
        meta["xml_references"] = refs
        plan = output_plan(meta, review)
        spacings = [float(value) for value in review["proposed_spacing_m"]]
        candidates = [
            derive_candidate(sid, review, source_def, dependencies, meta, label, dp)
            for label, dp in zip(LABELS, spacings)
        ]
        records.append({
            "sentinel_id": sid,
            "family_id": review["family"],
            "physical_case_id": review["source_physical_case_id"],
            "current_identity": {
                "family_id": row["family_id"],
                "physical_case_id": row["physical_case_id"],
                "runtime_case_alias": row["runtime_case_alias"],
                "frames": row["frames"],
                "particles": row["particles"],
                "actual_time_window_s": row["actual_time_window_s"],
                "trajectory_producer_sha256": row["trajectory"]["producer_declared_sha256"],
                "trajectory_mtime_ns": row["trajectory"]["mtime_ns"],
                "raw_root": row["raw_root"],
                "generated_xml_catalog_record": generated_record,
            },
            "source_binding": meta["source_binding"],
            "generated_xml_meta": meta["generated_xml_meta"],
            "generated_mass_semantics": meta["generated_mass_semantics"],
            "historical_solver_controls": meta["historical_solver_controls"],
            "xml_references": refs,
            "preflight_scope": {
                "three_spatial_grid": spacings,
                "same_cfl": meta["historical_solver_controls"]["xml_controls"]["cflnumber"],
                "half_cfl": review.get("proposed_half_cfl", "UNKNOWN"),
                "full_time_window_s": plan["full_physical_time_window_s"],
                "task_error": "UNKNOWN until the physical observation task is evaluated",
                "domain_or_geometry_error": "UNKNOWN; GenCase copy checks do not qualify continuous geometry",
                "time_error": "UNKNOWN until observer-calibrated full-window same/half-CFL comparison",
                "output_error": "UNKNOWN until registered dense-cadence comparison over the full window",
            },
            "time_output_plan": plan,
            "candidates": candidates,
            "status": "PREPARED_GENCASE_INPUTS_NOT_RUN",
            "solver_started": False,
            "gpu_lease": "none",
            "full_time_hdf5_read": False,
            "observer_calibration": "NOT_RUN",
            "QI": "NOT_ASSESSED",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        })
    manifest = {
        "schema": SCHEMA,
        "status": "PREPARED_GENCASE_INPUTS_NOT_RUN",
        "source_resolution_policy": "fixed CURRENT336 physical identity and exact recorded GenCase/solver receipt input paths; no glob/latest/family fallback",
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
        "continuous_vs_intentional_rule": "Def draw/fill/domain/control and referenced assets remain byte-identical; dp/h/mass/count/lattice phase are intentional measured resolution outputs",
        "sentinels": records,
        "solver_started": False,
        "gpu_lease": "none",
        "full_time_hdf5_read": False,
    }
    atomic_json(INPUT_ROOT / "manifest.json", manifest)
    return manifest


def request_for(candidate: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    definition = Path(candidate["derived_inputs"]["definition"]["path"]).resolve()
    source = candidate["source_binding"]
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
        Path(source["generated_xml"]["path"]),
        Path(source["generated_bi4"]["path"]),
        Path(source["gencase_receipt"]["path"]),
        Path(source["solver_receipt"]["path"]),
        Path(source["source_definition"]["path"]),
        definition,
    ]
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
    return {
        "schema": REQUEST_SCHEMA,
        "family_id": candidate["family_id"],
        "case_id": candidate["case_id"],
        "attempt_id": candidate["case_id"].lower() + "-001",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 2,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": candidate["estimated_storage_bytes"],
        "worktree_root": str(REPO),
        "cwd": str(definition.parent),
        "command": [str(GENCASE), str(definition.with_suffix("")), "{attempt_root}/generated", "-save:all"],
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
            "estimated_new_storage_bytes": candidate["estimated_storage_bytes"],
        },
        "scope": {
            "sentinel_id": candidate["sentinel_id"],
            "physical_case_id": candidate["physical_case_id"],
            "continuous_source_identity": source,
            "three_spatial_grid_label": candidate["label"],
            "dp_m": candidate["dp_m"],
            "intentional_resolution_variation": candidate["intentional_resolution_variation"],
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
        print(json.dumps({"status": "PASS", "manifest": str(INPUT_ROOT / "manifest.json"), "candidates": 24}, ensure_ascii=False))
        return 0
    requests = emit_requests(manifest, args.emit_requests_dir)
    print(json.dumps({"status": "PASS", "requests": len(requests), "output_dir": str(args.emit_requests_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
