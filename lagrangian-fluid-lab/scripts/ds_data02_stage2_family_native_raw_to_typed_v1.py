#!/usr/bin/env python3
"""Generic source-bound native BI4 -> typed comparison worker for Stage2.

This forward worker covers family anchors whose first required step is native
raw reconstruction (currently F4 and F6).  It deliberately has no family
specific label operator.  The request is built from an exact v14 anchor plan:
the CURRENT row, generated GenCase XML, receipts, all top-level ``Part_*.bi4``
frames, and the typed producer HDF5 are bound by identity and statistics.

``prepare`` only reads JSON/XML and filesystem metadata.  ``run`` without
``--io-slot-approved`` emits a metadata preflight and opens neither BI4 nor
HDF5 content.  The approved path calls the checked-in ``ds_data02_f5_bi4``
converter once, records the raw tree before/after and per-frame evidence, and
asks that trusted converter to compare every typed dataset with the exact
CURRENT-bound HDF5.  A missing producer raw-tree digest stays UNKNOWN; the
worker never invents one.  F6 ``massbody`` is a rigid-body source field and
is never inferred from floating/support particle weights.

All output roots are new-only.  Reports are development evidence and retain
QI/QN/QE UNKNOWN.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.family-native-raw-to-typed-compare.v1"
REQUEST_SCHEMA = "ds02.stage2.family-native-raw-to-typed-compare-request.v1"
REPORT_SCHEMA = "ds02.stage2.family-native-raw-to-typed-compare-report.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
PENDING = "PENDING_PARENT_GUARD_CONTENT_SHA256"
HEX64 = set("0123456789abcdef")
FAMILIES = {"F4", "F6"}
FRAME_RE = __import__("re").compile(r"^Part_(\d{4})\.bi4$")


class FamilyNativeError(RuntimeError):
    """Raised when a family native request is incomplete or unsafe."""


def sha256_file(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any, *, drop: Sequence[str] = ()) -> str:
    excluded = set(drop)
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str,
    ).encode("utf-8")).hexdigest()


def _load_json(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise FamilyNativeError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise FamilyNativeError(f"JSON object required: {path}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    if target.exists():
        raise FamilyNativeError(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, default=str)
            stream.write("\n")
    except FileExistsError as error:
        raise FamilyNativeError(f"refusing to overwrite output: {target}") from error


def _sha(value: Any, name: str, *, allow_pending: bool = False) -> str | None:
    if allow_pending and value in (None, PENDING):
        return None
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise FamilyNativeError(f"{name} must be a lowercase SHA-256")
    return value


def _stat(path_value: Any, role: str, *, expected_sha: str | None = None,
          verify_hash: bool = False) -> dict[str, Any]:
    if not isinstance(path_value, str) or not path_value:
        raise FamilyNativeError(f"{role}.path is required")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise FamilyNativeError(f"{role} is missing: {path}")
    stat = path.stat()
    record: dict[str, Any] = {
        "role": role,
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if expected_sha not in (None, PENDING):
        record["sha256"] = expected_sha
        if verify_hash and sha256_file(path) != expected_sha:
            raise FamilyNativeError(f"{role} SHA differs")
        record["content_hash_status"] = "VERIFIED" if verify_hash else "PARENT_GUARD_REQUIRED"
    else:
        record["sha256"] = expected_sha
        record["content_hash_status"] = "UNKNOWN_PENDING_PARENT_GUARD"
    return record


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_run_out(receipt_path: Path) -> Path:
    """Resolve Run.out from the actual solver output argv only.

    ``receipt.output_root/Run.out`` is insufficient for workers whose command
    places output under ``solver_output``.  We use the command's output
    directory argument and require its Run.out to be inside the receipt scope;
    no neighboring-directory fallback is permitted.
    """
    receipt = _load_json(receipt_path)
    command = receipt.get("command")
    output_root_value = receipt.get("output_root")
    if not isinstance(command, list) or not command or not isinstance(output_root_value, str):
        raise FamilyNativeError("solver receipt command/output_root is required")
    output_root = Path(output_root_value).expanduser().resolve()
    candidates: list[Path] = []
    for value in command:
        if not isinstance(value, str) or not value.startswith("/"):
            continue
        directory = Path(value).expanduser().resolve()
        if not directory.is_dir() or not _is_under(directory, output_root):
            continue
        candidate = directory / "Run.out"
        if candidate.is_file():
            candidates.append(candidate)
    unique = sorted({path.resolve() for path in candidates}, key=str)
    if len(unique) != 1:
        raise FamilyNativeError(
            f"solver command must identify exactly one in-scope Run.out; found {unique}")
    return unique[0]


def _load_module(path: Path, name: str) -> Any:
    if not path.is_file():
        raise FamilyNativeError(f"bound module is missing: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FamilyNativeError(f"cannot import bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _plan_sources(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in plan.get("source_bindings", []):
        if not isinstance(entry, Mapping) or not isinstance(entry.get("role"), str):
            raise FamilyNativeError("anchor source binding is malformed")
        role = str(entry["role"])
        if role in result:
            raise FamilyNativeError(f"duplicate anchor source role: {role}")
        result[role] = dict(entry)
    return result


def _xml_mass_semantics(xml_path: Path, family: str) -> dict[str, Any]:
    try:
        root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise FamilyNativeError(f"cannot parse generated XML: {xml_path}: {error}") from error
    floating: list[dict[str, Any]] = []
    for node in root.findall(".//floatings/floating"):
        mass_node = node.find("massbody")
        inertia_node = node.find("inertia")
        mass = None if mass_node is None else mass_node.get("value")
        inertia = None if inertia_node is None else {
            axis: inertia_node.get(axis) for axis in ("x", "y", "z")
        }
        floating.append({
            "scope": "rigid_body_definition",
            "mkbound": node.get("mkbound"),
            "mk": node.get("mk"),
            "massbody_kg": None if mass is None else float(mass),
            "massbody_source": "generated_xml.<floating>.massbody",
            "inertia": inertia,
            "particle_mass_attribute": node.findtext("masspart"),
        })
    particle_records: list[dict[str, Any]] = []
    for node in root.findall(".//execution/particles/floating"):
        mass_node = node.find("masspart")
        body_node = node.find("massbody")
        particle_records.append({
            "scope": "typed_particle_block",
            "mkbound": node.get("mkbound"),
            "mk": node.get("mk"),
            "begin": node.get("begin"),
            "count": node.get("count"),
            "masspart_kg": None if mass_node is None else mass_node.get("value"),
            "massbody_kg": None if body_node is None else body_node.get("value"),
        })
    rigid = {
        "status": "EXPLICIT_XML_MASSBODY" if floating else "NOT_DECLARED_UNKNOWN",
        "massbody_records": floating,
        "typed_particle_block_records": particle_records,
        "particle_sum_as_rigid_mass": False,
        "pose_velocity_credit": "UNKNOWN_UNTIL_EXPLICIT_FLOATING_TELEMETRY_FIELD_MAP",
    }
    return {
        "particle_mass_source": "native BI4 header MassFluid(type=3) / MassBound(type=0,1,2); type/MK ranges from generated XML",
        "support_weight_source": "native boundary/support particle weights and PartFloatInfo when present; not rigid mass",
        "rigid_body_mass_source": "generated XML massbody records" if floating else "no explicit rigid massbody source",
        "rigid_body_inference_from_particle_sum": False,
        "rigid_body": rigid,
        "typed_particle_block_records": particle_records,
        "family": family,
    }


def _current_binding(plan: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    anchor = plan.get("anchor_case")
    if not isinstance(anchor, Mapping):
        raise FamilyNativeError("anchor_case is required")
    current = sources.get("current_catalog")
    trajectory = sources.get("trajectory_h5")
    if not isinstance(current, Mapping) or not isinstance(trajectory, Mapping):
        raise FamilyNativeError("CURRENT and trajectory_h5 source bindings are required")
    catalog_path = Path(str(current["path"])).expanduser().resolve()
    catalog = _load_json(catalog_path)
    cases = catalog.get("cases")
    index = anchor.get("current_index")
    if isinstance(index, bool) or not isinstance(index, int) or not isinstance(cases, list) or index < 0 or index >= len(cases):
        raise FamilyNativeError("CURRENT case index is malformed")
    row = cases[index]
    if not isinstance(row, Mapping):
        raise FamilyNativeError("CURRENT row is malformed")
    for key in ("family_id", "physical_case_id", "frames", "particles"):
        expected = anchor.get(key) if key in anchor else anchor.get("physical_case_id")
        if key == "physical_case_id":
            expected = anchor.get("physical_case_id")
        elif key == "family_id":
            expected = plan.get("family_id")
        if row.get(key) != expected:
            raise FamilyNativeError(f"CURRENT row {key} differs from exact anchor")
    row_trajectory = row.get("trajectory")
    if not isinstance(row_trajectory, Mapping) or not isinstance(row_trajectory.get("path"), str):
        raise FamilyNativeError("CURRENT row trajectory binding is missing")
    h5_path = Path(str(trajectory["path"])).expanduser().resolve()
    if Path(str(row_trajectory["path"])).expanduser().resolve() != h5_path:
        raise FamilyNativeError("trajectory path differs from CURRENT producer binding")
    producer_sha = row_trajectory.get("producer_declared_sha256") or trajectory.get("producer_declared_sha256")
    _sha(producer_sha, "trajectory_h5.producer_declared_sha256")
    return {
        "case_index": index,
        "family_id": row.get("family_id"),
        "physical_case_id": row.get("physical_case_id"),
        "runtime_case_alias": row.get("runtime_case_alias"),
        "frames": row.get("frames"),
        "particles": row.get("particles"),
        "identity_key": "(Zone,Idp)",
        "catalog": _stat(current.get("path"), "current_catalog", expected_sha=current.get("sha256")),
        "trajectory_h5": _stat(trajectory.get("path"), "trajectory_h5", expected_sha=producer_sha),
        "producer_sha_scope": "CURRENT producer_declared_sha256; parent guard must verify content before comparison",
    }


def build_request(anchor_plan_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    plan_path = Path(anchor_plan_path).expanduser().resolve()
    plan = _load_json(plan_path)
    if plan.get("schema") != "ds02.stage2.family-raw-anchor-plan.v1":
        raise FamilyNativeError("unsupported anchor plan schema")
    family = str(plan.get("family_id"))
    if family not in FAMILIES:
        raise FamilyNativeError(f"forward worker currently supports only {sorted(FAMILIES)}")
    sources = _plan_sources(plan)
    current = _current_binding(plan, sources)
    generated = sources.get("generated_xml")
    gencase_receipt = sources.get("gencase_receipt")
    solver_receipt = sources.get("solver_receipt")
    owner = sources.get("owner_metadata")
    if not all(isinstance(item, Mapping) for item in (generated, gencase_receipt, solver_receipt, owner)):
        raise FamilyNativeError("generated XML/receipts/owner metadata are required")
    raw = plan.get("raw_anchor")
    if not isinstance(raw, Mapping) or raw.get("raw_root_exists") is not True:
        raise FamilyNativeError("raw anchor root is not source-bound")
    raw_root = Path(str(raw["raw_root"])).expanduser().resolve()
    frame_paths = sorted(
        (path for path in raw_root.glob("Part_*.bi4") if path.is_file()),
        key=lambda path: path.name,
    )
    expected_frames = int(raw.get("frame_count_expected", 0))
    observed_indices = [int(FRAME_RE.match(path.name).group(1)) for path in frame_paths
                        if FRAME_RE.match(path.name)]
    if len(frame_paths) != expected_frames or observed_indices != list(range(expected_frames)):
        raise FamilyNativeError("raw Part_*.bi4 list is not the exact contiguous CURRENT frame set")
    frame_records = [{
        "frame": index,
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "mtime_ns": path.stat().st_mtime_ns,
        "sha256": PENDING,
        "content_hash_status": "UNKNOWN_PENDING_PARENT_GUARD",
    } for index, path in enumerate(frame_paths)]
    required_arrays: list[dict[str, Any]] = []
    for name in raw.get("required_source_arrays", []):
        path = raw_root / str(name)
        if not path.is_file():
            raise FamilyNativeError(f"required native source array is missing: {path}")
        role = "raw_frame_input" if FRAME_RE.match(path.name) else (
            "raw_provenance_partout" if path.name.startswith("PartOut_") else f"raw_header_{path.name}")
        required_arrays.append(_stat(str(path), role))
    run_out = _resolve_run_out(Path(str(solver_receipt["path"])))
    required_arrays.append(_stat(str(run_out), "solver_run_out", expected_sha=sha256_file(run_out)))
    module_path = Path(__file__).resolve().with_name("ds_data02_f5_bi4.py")
    decoder = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump").resolve()
    if not decoder.is_file():
        raise FamilyNativeError(f"trusted BI4 decoder is missing: {decoder}")
    converter_record = _stat(str(module_path), "raw_converter", expected_sha=sha256_file(module_path))
    decoder_record = _stat(str(decoder), "bi4_decoder", expected_sha=sha256_file(decoder))
    source_records: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for role, item in sources.items():
        path = Path(str(item["path"])).expanduser().resolve()
        if role == "trajectory_h5":
            continue
        if str(path) in seen_paths:
            continue
        seen_paths.add(str(path))
        source_records.append(_stat(str(path), role, expected_sha=item.get("sha256")))
    for record in required_arrays:
        if record["path"] not in seen_paths:
            source_records.append(record)
            seen_paths.add(record["path"])
    if converter_record["path"] not in seen_paths:
        source_records.append(converter_record)
    if decoder_record["path"] not in seen_paths:
        source_records.append(decoder_record)
    mass = _xml_mass_semantics(Path(str(generated["path"])).expanduser().resolve(), family)
    raw_total = sum(item["bytes"] for item in frame_records + required_arrays)
    expected_shape = {"frames": int(current["frames"]), "particles": int(current["particles"])}
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "request_id": f"{family.lower()}-s1-native-raw-to-typed-compare-v1-001",
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "family_id": family,
        "anchor_plan": {"path": str(plan_path), "sha256": sha256_file(plan_path)},
        "current_binding": current,
        "modules": {
            "raw_converter": converter_record,
            "worker": {"role": "worker", "path": str(Path(__file__).resolve()),
                        "sha256": sha256_file(Path(__file__).resolve()),
                        "content_hash_status": "PARENT_GUARD_REQUIRED"},
        },
        "decoder": decoder_record,
        "source_files": source_records,
        "raw_binding": {
            "data_root": str(raw_root),
            "frame_pattern": "Part_%04d.bi4",
            "frame_count": expected_frames,
            "frames": frame_records,
            "required_source_arrays": [item["path"] for item in required_arrays],
            "expected_raw_tree_sha256": None,
            "expected_raw_tree_status": "UNKNOWN_PENDING_PARENT_WORKER",
            "producer_tree_digest_invented": False,
            "before_after_policy": "worker records actual before/after tree digest and unchanged status",
        },
        "typed_reference_hdf5": current["trajectory_h5"],
        "typed_output_contract": {
            "expected_shape": expected_shape,
            "identity_key": "(Zone,Idp)",
            "structural_fields": ["time", "particle_id", "particle_zone", "valid", "type", "mk"],
            "numeric_fields": ["position", "velocity", "density", "mass", "pressure"],
            "initial_fields": ["initial_type", "initial_mk", "initial_mass"],
            "particle_chunk": 65536,
            "time_source": "BI4 decoder TimeStep; compare complete saved timeline to CURRENT HDF5",
            "lifecycle": "valid=false retains Zone/Idp identity; state fields are unknown and must not receive label credit",
            "raw_header_fields": ["CaseNp", "Dp", "B", "Rhop0", "Gamma", "MassBound", "MassFluid", "Npiece", "Piece", "NpDynamic", "ReuseIds", "PeriMode", "TimeStep"],
        },
        "mass_semantics": mass,
        "labels": {
            "status": "PENDING_FAMILY_SPECIFIC_OPERATOR",
            "receiver_geometry_inference": "FORBIDDEN",
            "typed_comparison_is_prerequisite": True,
        },
        "source_closure": {
            "current_catalog": sources["current_catalog"],
            "generated_xml": sources["generated_xml"],
            "gencase_receipt": sources["gencase_receipt"],
            "solver_receipt": sources["solver_receipt"],
            "owner_metadata": sources["owner_metadata"],
            "conversion_report": sources.get("conversion_report"),
            "manifest": sources.get("manifest"),
            "xmf": sources.get("xmf"),
            "raw_source_expected_tree": "UNKNOWN; no producer digest was available in the anchor plan",
        },
        "input_files": [],
        "input_hashes": {},
        "input_hash_scopes": {},
        "resource_request": {
            "cpu": 1,
            "max_wall_seconds": 5400,
            "max_rss_bytes": 5 * 1024**3,
            "new_storage_budget_bytes": 16 * 1024**3,
            "raw_tree_bytes_from_stat": raw_total,
            "reference_hdf5_bytes": current["trajectory_h5"]["bytes"],
            "rss_enforcement": "parent guard records ru_maxrss; no hard RSS claim",
            "hdf5_read": "full comparison only after parent IO slot",
        },
        "source_hashes_preverified_by_parent": False,
        "execution": {
            "entrypoint": str(Path(__file__).resolve()),
            "metadata_command": [
                sys.executable, str(Path(__file__).resolve()), "prepare",
                "--request", "<request>", "--output", "<metadata-output>",
            ],
            "full_parent_guard_command": [
                sys.executable, str(Path(__file__).resolve()), "run",
                "--request", "<request>", "--output-dir", "<new-output-root>",
                "--io-slot-approved",
            ],
            "full_command_scope": "trusted converter reads each bound Part_*.bi4 once, writes new typed HDF5, and compares every typed field to the exact CURRENT trajectory",
        },
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": UNKNOWN,
        "limitations": [
            "F4/F6 raw tree expected digest is UNKNOWN until parent worker records it; no SHA is invented",
            "PartOut/RunPARTs and PartFloatInfo are provenance/header inputs, never substitutes for Part_*.bi4 typed frames",
            "F6 massbody is XML rigid-body mass; support/floating particle weights are separate and pose/orientation remains UNKNOWN",
            "family-specific labels, recovery equivalence, cross-resolution transfer, and QI/QN/QE remain UNKNOWN",
        ],
    }
    input_records: list[dict[str, Any]] = list(source_records)
    input_records.extend(frame_records)
    input_records.append(current["trajectory_h5"])
    input_records.append(request["modules"]["worker"])
    seen_input: set[str] = set()
    for item in input_records:
        path = str(item["path"])
        if path in seen_input:
            continue
        seen_input.add(path)
        request["input_files"].append(path)
        digest = item.get("sha256")
        request["input_hashes"][path] = digest
        request["input_hash_scopes"][path] = (
            "PENDING_PARENT_GUARD_CONTENT_SHA256" if digest in (None, PENDING) else
            ("CURRENT_PRODUCER_DECLARED_SHA256_PARENT_VERIFY" if path == current["trajectory_h5"]["path"] else "CONTENT_SHA256")
        )
    request["sha256"] = canonical_sha({key: value for key, value in request.items() if key != "sha256"})
    _write_new(output_path, request)
    return {"path": str(Path(output_path).expanduser().resolve()), "sha256": request["sha256"],
            "family_id": family, "frames": expected_frames, "particles": int(current["particles"])}


def _validate_xml_and_shape(request: Mapping[str, Any]) -> dict[str, Any]:
    xml = next((item for item in request.get("source_files", [])
                if isinstance(item, Mapping) and item.get("role") == "generated_xml"), None)
    if not isinstance(xml, Mapping):
        raise FamilyNativeError("generated_xml source binding is required")
    try:
        root = ET.parse(str(xml["path"])).getroot()
    except (OSError, ET.ParseError) as error:
        raise FamilyNativeError(f"generated XML cannot be parsed: {error}") from error
    node = root.find(".//execution/particles") or root.find(".//particles")
    expected = request["typed_output_contract"]["expected_shape"]
    if node is None or int(node.get("np", -1)) != int(expected["particles"]):
        raise FamilyNativeError("generated XML particle count differs from frozen CURRENT shape")
    return {"generated_xml": str(xml["path"]), "particles": int(expected["particles"]),
            "xml_np": int(node.get("np"))}


def _validate_request(request: Mapping[str, Any], *, verify_sources: bool) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA:
        raise FamilyNativeError("unsupported family native request schema")
    if request.get("status") != "READY_FOR_PARENT_GUARD" or request.get("role") != "DEVELOPMENT":
        raise FamilyNativeError("request must remain development and parent-guard ready")
    family = request.get("family_id")
    if family not in FAMILIES:
        raise FamilyNativeError("only F4/F6 are supported by this worker")
    if request.get("qualification") != UNKNOWN or request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise FamilyNativeError("model/CFD or qualification credit is forbidden")
    declared = _sha(request.get("sha256"), "request.sha256")
    actual = canonical_sha({key: value for key, value in request.items() if key != "sha256"})
    if declared != actual:
        raise FamilyNativeError("request canonical SHA differs")
    binding = request.get("current_binding")
    if not isinstance(binding, Mapping):
        raise FamilyNativeError("current_binding is required")
    expected = request.get("typed_output_contract", {}).get("expected_shape")
    if not isinstance(expected, Mapping) or int(binding.get("frames", -1)) != int(expected.get("frames", -2)) or int(binding.get("particles", -1)) != int(expected.get("particles", -2)):
        raise FamilyNativeError("CURRENT shape and typed shape differ")
    _stat(binding.get("catalog", {}).get("path"), "current_catalog",
          expected_sha=binding.get("catalog", {}).get("sha256"), verify_hash=verify_sources)
    h5 = binding.get("trajectory_h5")
    if not isinstance(h5, Mapping):
        raise FamilyNativeError("typed_reference_hdf5 binding is required")
    h5_record = _stat(h5.get("path"), "trajectory_h5", expected_sha=h5.get("sha256"), verify_hash=False)
    if h5_record["bytes"] != int(h5.get("bytes", -1)) or h5_record["mtime_ns"] != int(h5.get("mtime_ns", -1)):
        raise FamilyNativeError("typed reference HDF5 stat differs")
    raw = request.get("raw_binding")
    if not isinstance(raw, Mapping):
        raise FamilyNativeError("raw_binding is required")
    root = Path(str(raw.get("data_root", ""))).expanduser().resolve()
    if not root.is_dir():
        raise FamilyNativeError(f"raw data root is missing: {root}")
    frames = raw.get("frames")
    if not isinstance(frames, list) or len(frames) != int(raw.get("frame_count", -1)):
        raise FamilyNativeError("raw frame list is incomplete")
    expected_paths: list[Path] = []
    for index, item in enumerate(frames):
        if not isinstance(item, Mapping) or item.get("frame") != index:
            raise FamilyNativeError("raw frame records must be contiguous from zero")
        path = Path(str(item.get("path", ""))).expanduser().resolve()
        match = FRAME_RE.match(path.name)
        if path.parent != root or match is None or int(match.group(1)) != index:
            raise FamilyNativeError(f"raw frame {index} is not exact Part_%04d.bi4" % index)
        record = _stat(str(path), f"raw_frame_{index:04d}", expected_sha=item.get("sha256"), verify_hash=verify_sources and item.get("sha256") is not None)
        if record["bytes"] != int(item.get("bytes", -1)) or record["mtime_ns"] != int(item.get("mtime_ns", -1)):
            raise FamilyNativeError(f"raw frame {index} stat differs")
        expected_paths.append(path)
    observed = sorted((path.resolve() for path in root.glob("Part_*.bi4") if path.is_file()), key=str)
    if observed != expected_paths:
        raise FamilyNativeError("raw frame list does not equal all top-level Part_*.bi4 files")
    expected_tree = raw.get("expected_raw_tree_sha256")
    if expected_tree not in (None, PENDING):
        _sha(expected_tree, "raw_binding.expected_raw_tree_sha256")
    _validate_xml_and_shape(request)
    mass = request.get("mass_semantics")
    if not isinstance(mass, Mapping) or mass.get("rigid_body_inference_from_particle_sum") is not False:
        raise FamilyNativeError("rigid body mass must never be inferred from particle sums")
    for key in ("particle_mass_source", "support_weight_source", "rigid_body_mass_source"):
        if not isinstance(mass.get(key), str) or not mass[key]:
            raise FamilyNativeError(f"mass_semantics.{key} is required")
    if family == "F6" and not any("PartFloatInfo.ibi4" in str(path) for path in raw.get("required_source_arrays", [])):
        raise FamilyNativeError("F6 PartFloatInfo.ibi4 must be source-bound")
    for item in request.get("source_files", []):
        if not isinstance(item, Mapping):
            raise FamilyNativeError("source_files entry is malformed")
        _stat(item.get("path"), str(item.get("role")), expected_sha=item.get("sha256"),
              verify_hash=verify_sources and item.get("sha256") is not None)
    decoder = request.get("decoder")
    module = request.get("modules", {}).get("raw_converter")
    for role, item in (("decoder", decoder), ("raw_converter", module)):
        if not isinstance(item, Mapping):
            raise FamilyNativeError(f"{role} binding is required")
        _stat(item.get("path"), role, expected_sha=item.get("sha256"), verify_hash=verify_sources)
    return {"family": family, "frames": int(expected["frames"]), "particles": int(expected["particles"]),
            "raw_root": root, "reference_hdf5": Path(str(h5["path"])).expanduser().resolve(),
            "generated_xml": Path(str(next(item for item in request["source_files"] if item.get("role") == "generated_xml")["path"])).expanduser().resolve(),
            "solver_receipt": Path(str(next(item for item in request["source_files"] if item.get("role") == "solver_receipt")["path"])).expanduser().resolve(),
            "gencase_receipt": Path(str(next(item for item in request["source_files"] if item.get("role") == "gencase_receipt")["path"])).expanduser().resolve(),
            "owner_metadata": Path(str(next(item for item in request["source_files"] if item.get("role") == "owner_metadata")["path"])).expanduser().resolve(),
            "solver_run_out": Path(str(next(item for item in request["source_files"] if item.get("role") == "solver_run_out")["path"])).expanduser().resolve(),
            "decoder": Path(str(decoder["path"])).expanduser().resolve(),
            "raw_converter": Path(str(module["path"])).expanduser().resolve(),
            "expected_raw_tree": expected_tree}


def _resource_snapshot() -> dict[str, float]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {"user_seconds": float(usage.ru_utime), "system_seconds": float(usage.ru_stime),
            "max_rss_kib": float(usage.ru_maxrss)}


def prepare_report(request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load_json(request_file)
    bound = _validate_request(request, verify_sources=False)
    report = {
        "schema": REPORT_SCHEMA,
        "status": "READY_FOR_PARENT_IO_SLOT",
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "source_closure": {
            "family_id": bound["family"], "frames": bound["frames"], "particles": bound["particles"],
            "raw_root": str(bound["raw_root"]), "expected_raw_tree_sha256": bound["expected_raw_tree"],
            "expected_raw_tree_status": "UNKNOWN_PENDING_PARENT_WORKER" if bound["expected_raw_tree"] is None else "BOUND",
            "current_reference_shape_bound": True,
        },
        "execution_boundary": {"raw_opened": False, "hdf5_opened": False,
                                "converter_invoked": False, "family_labels_invoked": False,
                                "model_invoked": False, "cfd_invoked": False,
                                "parent_stage2guard_required": True},
        "typed_comparison": {"status": "PENDING_PARENT_IO_SLOT", "all_frames": True,
                              "identity_key": "(Zone,Idp)", "lifecycle": "valid=false retains identity; state unknown"},
        "labels": {"status": "PENDING_FAMILY_SPECIFIC_OPERATOR"},
        "mass_semantics": request["mass_semantics"],
        "qualification": UNKNOWN,
    }
    report["report_sha256"] = canonical_sha(report)
    _write_new(output_path, report)
    return report


def run(request_path: Path | str, output_dir: Path | str, *, io_slot_approved: bool = False) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load_json(request_file)
    bound = _validate_request(request, verify_sources=bool(io_slot_approved and not request.get("source_hashes_preverified_by_parent")))
    target = Path(output_dir).expanduser().resolve()
    if target.exists():
        raise FamilyNativeError(f"refusing to use existing output directory: {target}")
    target.mkdir(parents=True, exist_ok=False)
    if not io_slot_approved:
        report = {
            "schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
            "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
            "execution_boundary": {"raw_opened": False, "hdf5_opened": False,
                                    "converter_invoked": False, "family_labels_invoked": False,
                                    "model_invoked": False, "cfd_invoked": False},
            "source_closure": {"family_id": bound["family"], "frames": bound["frames"],
                                "particles": bound["particles"], "expected_raw_tree_sha256": bound["expected_raw_tree"]},
            "qualification": UNKNOWN,
        }
        _write_new(target / "metadata-preflight.json", report)
        return report
    started = time.monotonic()
    before = _resource_snapshot()
    converter = _load_module(bound["raw_converter"], "_ds02_family_bound_converter_v1")
    run_out = bound["solver_run_out"]
    typed_path = target / "typed-reconstructed.h5"
    converter_report_path = target / "raw-converter-report.json"
    converter_report = converter.convert_direct(
        data_root=bound["raw_root"], generated_xml=bound["generated_xml"], output=typed_path,
        report_path=converter_report_path, decoder=bound["decoder"], partvtk=None,
        validation_dir=None, solver_log=run_out, solver_receipt=bound["solver_receipt"],
        gencase_receipt=bound["gencase_receipt"], owner_metadata=bound["owner_metadata"],
        reference_hdf5=bound["reference_hdf5"], run_partvtk=False,
        particle_chunk=65536,
    )
    raw_tree = converter_report.get("source_provenance", {}).get("raw_tree", {})
    actual_before = raw_tree.get("before_tree_sha256")
    actual_after = raw_tree.get("after_tree_sha256")
    if actual_before != actual_after or raw_tree.get("unchanged") is not True:
        raise FamilyNativeError("raw source tree changed during conversion")
    if bound["expected_raw_tree"] is not None and actual_before != bound["expected_raw_tree"]:
        raise FamilyNativeError("raw source tree differs from declared producer digest")
    comparison = converter_report.get("reference_hdf5_comparison")
    report = {
        "schema": REPORT_SCHEMA,
        "status": "COMPLETE_DEVELOPMENT_UNKNOWN",
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "source_closure": {"family_id": bound["family"], "frames": bound["frames"], "particles": bound["particles"],
                            "raw_tree": {"expected": bound["expected_raw_tree"], "actual_before": actual_before,
                                         "actual_after": actual_after, "expected_status": "UNKNOWN_UNTIL_WORKER" if bound["expected_raw_tree"] is None else "BOUND"},
                            "reference_hdf5": str(bound["reference_hdf5"])},
        "raw_to_typed": {"status": "COMPLETE", "converter_report": str(converter_report_path),
                         "converter_report_sha256": sha256_file(converter_report_path)},
        "typed_output": {"path": str(typed_path), "bytes": typed_path.stat().st_size,
                          "sha256": sha256_file(typed_path)},
        "typed_full_current_compare": comparison,
        "labels": {"status": "PENDING_FAMILY_SPECIFIC_OPERATOR", "receiver_geometry_inference": "FORBIDDEN"},
        "mass_semantics": request["mass_semantics"],
        "execution_boundary": {"raw_opened": True, "hdf5_opened": True, "converter_invoked": True,
                                "family_labels_invoked": False, "model_invoked": False, "cfd_invoked": False,
                                "parent_stage2guard_required": True},
        "resource": {"wall_seconds": time.monotonic() - started,
                      "usage": {"before": before, "after": _resource_snapshot()}},
        "qualification": UNKNOWN,
        "limitations": [
            "raw-tree producer expected digest was UNKNOWN when request was prepared; actual worker before/after digest is retained",
            "F6 rigid body mass is XML massbody; PartFloatInfo orientation/pose semantics and scientific labels remain UNKNOWN",
            "no family-specific task labels or QI/QN/QE credit is granted",
        ],
    }
    report["report_sha256"] = canonical_sha(report)
    _write_new(target / "raw-to-typed-compare-report.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("build-request")
    prepare.add_argument("--anchor-plan", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    metadata = sub.add_parser("prepare")
    metadata.add_argument("--request", type=Path, required=True)
    metadata.add_argument("--output", type=Path, required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--request", type=Path, required=True)
    execute.add_argument("--output-dir", type=Path, required=True)
    execute.add_argument("--io-slot-approved", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            result = build_request(args.anchor_plan, args.output)
        elif args.command == "prepare":
            result = prepare_report(args.request, args.output)
        else:
            result = run(args.request, args.output_dir, io_slot_approved=args.io_slot_approved)
    except (FamilyNativeError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": result.get("schema", REQUEST_SCHEMA),
                      "status": result.get("status"), "family_id": result.get("family_id"),
                      "qualification": result.get("qualification", UNKNOWN)}, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
