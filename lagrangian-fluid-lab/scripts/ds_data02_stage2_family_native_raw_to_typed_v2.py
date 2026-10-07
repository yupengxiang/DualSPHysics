#!/usr/bin/env python3
"""Generic source-bound BI4 stream requests for the remaining Stage2 families.

This is an additive forward version of the v1 native stream worker.  It covers
one explicit raw anchor for F1, F3, F5, and F7.  The builder only reads JSON,
XML, receipts, and filesystem metadata; it never reads BI4 or HDF5 content.
The parent Stage2 guard may later invoke the same request with an approved I/O
slot, in which case the already-bound converter streams every ``Part_*.bi4``
frame and compares the resulting typed trajectory against the exact CURRENT
producer.  No family-specific observer, receiver geometry, or qualification
credit is produced here.

F5's 16-second window and motion/curve tail are retained as source evidence.
The worker does not truncate, extrapolate, or reconstruct that curve from a
nominal case name; the solver receipt, generated XML, and raw PartMotionRef
array remain bound inputs.  ``PartOut``/``RunPARTs`` are provenance only and
cannot satisfy a frame binding.  Expected raw-tree SHA remains unknown until
the parent worker hashes the exact tree.
"""
from __future__ import annotations

# The v1 implementation is kept immutable because it has already been
# consumed.  Reuse its audited source-bound mechanics, then apply the v2
# family scope and semantics below.  Importing it does not read any dataset.
import importlib.util
from pathlib import Path
from typing import Any, Mapping, Sequence

_V1_PATH = Path(__file__).with_name("ds_data02_stage2_family_native_raw_to_typed_v1.py")
_SPEC = importlib.util.spec_from_file_location("_ds02_family_native_v1_for_v2", _V1_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - packaging error
    raise ImportError(f"cannot load immutable v1 worker: {_V1_PATH}")
_v1 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_v1)


SCHEMA = "ds02.stage2.family-native-raw-to-typed-compare.v2"
REQUEST_SCHEMA = "ds02.stage2.family-native-raw-to-typed-compare-request.v2"
REPORT_SCHEMA = "ds02.stage2.family-native-raw-to-typed-compare-report.v2"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
PENDING = _v1.PENDING
FAMILIES = {"F1", "F3", "F5", "F7"}
FRAME_RE = _v1.FRAME_RE


class FamilyNativeV2Error(_v1.FamilyNativeError):
    """Raised when a v2 request is incomplete or unsafe."""


# Keep the helpers as aliases so source behavior remains auditable and the
# forward module has a small, explicit diff from the consumed implementation.
sha256_file = _v1.sha256_file
canonical_sha = _v1.canonical_sha
_load_json = _v1._load_json
_write_new = _v1._write_new
_sha = _v1._sha
_stat = _v1._stat
_plan_sources = _v1._plan_sources
_xml_mass_semantics = _v1._xml_mass_semantics
_current_binding = _v1._current_binding
_resolve_run_out = _v1._resolve_run_out


def _f5_control_tail(plan: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Return explicit F5 tail provenance without interpreting the curve.

    The v14 plan intentionally does not assert a duration/angle.  A request
    therefore records the actual 16 s window, the PartMotionRef source role,
    and the receipt/XML paths.  A missing motion source is an error for F5;
    no nominal ``ROT`` or other case alias is substituted.
    """
    anchor = plan.get("anchor_case")
    raw = plan.get("raw_anchor")
    if not isinstance(anchor, Mapping) or not isinstance(raw, Mapping):
        raise FamilyNativeV2Error("F5 anchor_case/raw_anchor are required")
    window = anchor.get("actual_time_window_s")
    if not (isinstance(window, list) and len(window) == 2 and
            all(isinstance(value, (int, float)) for value in window) and
            float(window[1]) > float(window[0])):
        raise FamilyNativeV2Error("F5 actual_time_window_s must be a finite ordered pair")
    if abs(float(window[1]) - 16.0) > 0.01:
        raise FamilyNativeV2Error("F5 anchor must retain the actual approximately-16 s window")
    names = [str(value) for value in raw.get("observed_entry_names_metadata_only", [])]
    if "PartMotionRef.ibi4" not in names:
        raise FamilyNativeV2Error("F5 PartMotionRef.ibi4 must remain source-bound")
    return {
        "status": "BOUND_METADATA_ONLY; CURVE_TAIL_PENDING_PARENT_RAW_READ",
        "actual_time_window_s": [float(window[0]), float(window[1])],
        "frame_count": int(raw.get("frame_count_expected", -1)),
        "motion_source_role": "raw_header_PartMotionRef.ibi4",
        "tail_policy": "preserve native PartMotionRef tail and solver receipt; no truncation or extrapolation",
        "duration_semantics": "actual saved table coverage from anchor plan; motion duration/hold must be read from bound source",
        "nominal_case_alias_is_not_control": True,
        "control_source_roles": [
            sources.get("generated_xml", {}).get("role"),
            sources.get("solver_receipt", {}).get("role"),
            "raw_header_PartMotionRef.ibi4",
        ],
    }


def _forward_sources(plan: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]], family: str) -> dict[str, Any]:
    raw = plan.get("raw_anchor")
    if not isinstance(raw, Mapping):
        raise FamilyNativeV2Error("raw_anchor is required")
    required = [str(value) for value in raw.get("required_source_arrays", [])]
    if "Part_0000.bi4" not in required:
        raise FamilyNativeV2Error("Part_0000.bi4 is required raw source")
    # ``PartOut_000.obi4`` is deliberately allowed in the source list as a
    # provenance/header record.  The frame validator below only accepts exact
    # ``Part_%04d.bi4`` paths, so this record can never substitute for a frame.
    if family in {"F5", "F7"} and "PartMotionRef.ibi4" not in required:
        raise FamilyNativeV2Error(f"{family} motion source must remain explicitly bound")
    result: dict[str, Any] = {
        "frame_input_policy": "top-level contiguous Part_%04d.bi4 only",
        "provenance_only_names": ["PartOut_*.obi4", "RunPARTs", "PartFloatInfo.ibi4"],
        "required_source_arrays": required,
        "expected_raw_tree_sha256": None,
        "expected_raw_tree_status": "UNKNOWN_PENDING_PARENT_WORKER",
        "producer_tree_digest_invented": False,
    }
    if family == "F5":
        result["motion_control_tail"] = _f5_control_tail(plan, sources)
    else:
        result["motion_control_tail"] = {
            "status": "NOT_FAMILY_LABELLED; typed_stream_only",
            "nominal_case_alias_is_not_control": True,
        }
    return result


def build_request(anchor_plan_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    """Build a v2 metadata-only request for F1/F3/F5/F7."""
    plan_path = Path(anchor_plan_path).expanduser().resolve()
    plan = _load_json(plan_path)
    if plan.get("schema") != "ds02.stage2.family-raw-anchor-plan.v1":
        raise FamilyNativeV2Error("unsupported anchor plan schema")
    family = str(plan.get("family_id"))
    if family not in FAMILIES:
        raise FamilyNativeV2Error("v2 stream supports only F1/F3/F5/F7; F2 receiver semantics are excluded")
    sources = _plan_sources(plan)
    current = _current_binding(plan, sources)
    required_roles = ("generated_xml", "gencase_receipt", "solver_receipt", "owner_metadata")
    if any(not isinstance(sources.get(role), Mapping) for role in required_roles):
        raise FamilyNativeV2Error("generated XML/receipts/owner metadata are required")
    raw = plan.get("raw_anchor")
    if not isinstance(raw, Mapping) or raw.get("raw_root_exists") is not True:
        raise FamilyNativeV2Error("raw anchor root is not source-bound")
    raw_root = Path(str(raw["raw_root"])).expanduser().resolve()
    frame_paths = sorted((path for path in raw_root.glob("Part_*.bi4") if path.is_file()), key=lambda path: path.name)
    expected_frames = int(raw.get("frame_count_expected", 0))
    observed_indices = [int(FRAME_RE.match(path.name).group(1)) for path in frame_paths if FRAME_RE.match(path.name)]
    if len(frame_paths) != expected_frames or observed_indices != list(range(expected_frames)):
        raise FamilyNativeV2Error("raw Part_*.bi4 list is not the exact contiguous CURRENT frame set")
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
            raise FamilyNativeV2Error(f"required native source array is missing: {path}")
        role = "raw_frame_input" if FRAME_RE.match(path.name) else (
            "raw_provenance_partout" if path.name.startswith("PartOut_") else f"raw_header_{path.name}")
        required_arrays.append(_stat(str(path), role))
    run_out = _resolve_run_out(Path(str(sources["solver_receipt"]["path"])))
    required_arrays.append(_stat(str(run_out), "solver_run_out", expected_sha=sha256_file(run_out)))
    module_path = Path(__file__).resolve().with_name("ds_data02_f5_bi4.py")
    decoder = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump").resolve()
    if not decoder.is_file():
        raise FamilyNativeV2Error(f"trusted BI4 decoder is missing: {decoder}")
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
    for record in (converter_record, decoder_record):
        if record["path"] not in seen_paths:
            source_records.append(record)
            seen_paths.add(record["path"])
    mass = _xml_mass_semantics(Path(str(sources["generated_xml"]["path"])).expanduser().resolve(), family)
    raw_total = sum(item["bytes"] for item in frame_records + required_arrays)
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "request_id": f"{family.lower()}-s1-native-raw-to-typed-compare-v2-001",
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
            "v1_mechanics": {"role": "immutable_v1_helper", "path": str(_V1_PATH.resolve()),
                             "sha256": sha256_file(_V1_PATH), "content_hash_status": "PARENT_GUARD_REQUIRED"},
        },
        "decoder": decoder_record,
        "source_files": source_records,
        "raw_binding": {
            "data_root": str(raw_root),
            "frame_pattern": "Part_%04d.bi4",
            "frame_count": expected_frames,
            "frames": frame_records,
            "required_source_arrays": [item["path"] for item in required_arrays],
            **_forward_sources(plan, sources, family),
            "before_after_policy": "worker records actual before/after tree digest and unchanged status",
        },
        "typed_reference_hdf5": current["trajectory_h5"],
        "typed_output_contract": {
            "expected_shape": {"frames": int(current["frames"]), "particles": int(current["particles"])},
            "identity_key": "(Zone,Idp)",
            "structural_fields": ["time", "particle_id", "particle_zone", "valid", "type", "mk"],
            "numeric_fields": ["position", "velocity", "density", "mass", "pressure"],
            "initial_fields": ["initial_type", "initial_mk", "initial_mass"],
            "particle_chunk": 65536,
            "time_source": "BI4 decoder TimeStep; compare complete saved timeline to CURRENT HDF5",
            "lifecycle": "valid=false retains Zone/Idp identity; state fields are unknown and receive no label credit",
            "raw_header_fields": ["CaseNp", "Dp", "B", "Rhop0", "Gamma", "MassBound", "MassFluid", "Npiece", "Piece", "NpDynamic", "ReuseIds", "PeriMode", "TimeStep"],
        },
        "mass_semantics": mass,
        "labels": {
            "status": "PENDING_FAMILY_SPECIFIC_OPERATOR",
            "receiver_geometry_inference": "FORBIDDEN",
            "typed_comparison_is_prerequisite": True,
            "f2_receiver_operator_imported": False,
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
            "metadata_command": ["<python>", str(Path(__file__).resolve()), "prepare", "--request", "<request>", "--output", "<metadata-output>"],
            "full_parent_guard_command": ["<python>", str(Path(__file__).resolve()), "run", "--request", "<request>", "--output-dir", "<new-output-root>", "--io-slot-approved"],
            "full_command_scope": "trusted converter reads each bound Part_*.bi4 once, writes new typed HDF5, compares every typed field to exact CURRENT trajectory; no F2 receiver operator",
        },
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": UNKNOWN,
        "limitations": [
            "F1/F3/F5/F7 raw-tree expected digest is UNKNOWN until parent worker records it; no SHA is invented",
            "PartOut/RunPARTs and PartFloatInfo are provenance/header inputs, never substitutes for Part_*.bi4 typed frames",
            "F5 motion/control tail is source-bound but not interpreted before raw worker reads PartMotionRef and receipt/XML evidence",
            "family-specific labels, recovery equivalence, cross-resolution transfer, prospective split safety, and QI/QN/QE remain UNKNOWN",
        ],
    }
    input_records: list[dict[str, Any]] = list(source_records) + list(frame_records) + [current["trajectory_h5"], request["modules"]["worker"], request["modules"]["v1_mechanics"]]
    seen_input: set[str] = set()
    for item in input_records:
        path = str(item["path"])
        if path in seen_input:
            continue
        seen_input.add(path)
        request["input_files"].append(path)
        digest = item.get("sha256")
        request["input_hashes"][path] = digest
        request["input_hash_scopes"][path] = "PENDING_PARENT_GUARD_CONTENT_SHA256" if digest in (None, PENDING) else (
            "CURRENT_PRODUCER_DECLARED_SHA256_PARENT_VERIFY" if path == current["trajectory_h5"]["path"] else "CONTENT_SHA256")
    request["sha256"] = canonical_sha({key: value for key, value in request.items() if key != "sha256"})
    _write_new(output_path, request)
    return {"path": str(Path(output_path).expanduser().resolve()), "sha256": request["sha256"], "family_id": family, "frames": expected_frames, "particles": int(current["particles"])}


def _validate_request(request: Mapping[str, Any], *, verify_sources: bool) -> dict[str, Any]:
    """Validate v2 schema and source binding without reading BI4/HDF5 bytes."""
    if request.get("schema") != REQUEST_SCHEMA:
        raise FamilyNativeV2Error("unsupported family native v2 request schema")
    if request.get("status") != "READY_FOR_PARENT_GUARD" or request.get("role") != "DEVELOPMENT":
        raise FamilyNativeV2Error("request must remain development and parent-guard ready")
    family = request.get("family_id")
    if family not in FAMILIES:
        raise FamilyNativeV2Error("v2 supports only F1/F3/F5/F7")
    if request.get("qualification") != UNKNOWN or request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise FamilyNativeV2Error("model/CFD or qualification credit is forbidden")
    declared = _sha(request.get("sha256"), "request.sha256")
    actual = canonical_sha({key: value for key, value in request.items() if key != "sha256"})
    if declared != actual:
        raise FamilyNativeV2Error("request canonical SHA differs")
    # Reuse the immutable v1 validator only after replacing its family gate via
    # this local structural validation.  This keeps all path/stat checks in one
    # audited implementation while preventing F2 receiver leakage.
    expected = request.get("typed_output_contract", {}).get("expected_shape")
    binding = request.get("current_binding")
    if not isinstance(expected, Mapping) or not isinstance(binding, Mapping) or int(binding.get("frames", -1)) != int(expected.get("frames", -2)) or int(binding.get("particles", -1)) != int(expected.get("particles", -2)):
        raise FamilyNativeV2Error("CURRENT shape and typed shape differ")
    _v1._stat(binding.get("catalog", {}).get("path"), "current_catalog", expected_sha=binding.get("catalog", {}).get("sha256"), verify_hash=verify_sources)
    h5 = binding.get("trajectory_h5")
    if not isinstance(h5, Mapping):
        raise FamilyNativeV2Error("typed_reference_hdf5 binding is required")
    h5_record = _stat(h5.get("path"), "trajectory_h5", expected_sha=h5.get("sha256"), verify_hash=False)
    if h5_record["bytes"] != int(h5.get("bytes", -1)) or h5_record["mtime_ns"] != int(h5.get("mtime_ns", -1)):
        raise FamilyNativeV2Error("typed reference HDF5 stat differs")
    raw = request.get("raw_binding")
    if not isinstance(raw, Mapping):
        raise FamilyNativeV2Error("raw_binding is required")
    root = Path(str(raw.get("data_root", ""))).expanduser().resolve()
    if not root.is_dir():
        raise FamilyNativeV2Error(f"raw data root is missing: {root}")
    frames = raw.get("frames")
    if not isinstance(frames, list) or len(frames) != int(raw.get("frame_count", -1)):
        raise FamilyNativeV2Error("raw frame list is incomplete")
    expected_paths: list[Path] = []
    for index, item in enumerate(frames):
        if not isinstance(item, Mapping) or item.get("frame") != index:
            raise FamilyNativeV2Error("raw frame records must be contiguous from zero")
        path = Path(str(item.get("path", ""))).expanduser().resolve()
        match = FRAME_RE.match(path.name)
        if path.parent != root or match is None or int(match.group(1)) != index:
            raise FamilyNativeV2Error(f"raw frame {index} is not exact Part_%04d.bi4" % index)
        record = _stat(str(path), f"raw_frame_{index:04d}", expected_sha=item.get("sha256"), verify_hash=verify_sources and item.get("sha256") is not None)
        if record["bytes"] != int(item.get("bytes", -1)) or record["mtime_ns"] != int(item.get("mtime_ns", -1)):
            raise FamilyNativeV2Error(f"raw frame {index} stat differs")
        expected_paths.append(path)
    observed = sorted((path.resolve() for path in root.glob("Part_*.bi4") if path.is_file()), key=str)
    if observed != expected_paths:
        raise FamilyNativeV2Error("raw frame list does not equal all top-level Part_*.bi4 files")
    if family in {"F5", "F7"} and "PartMotionRef.ibi4" not in [Path(str(path)).name for path in raw.get("required_source_arrays", [])]:
        raise FamilyNativeV2Error(f"{family} motion source is not bound")
    if raw.get("expected_raw_tree_sha256") not in (None, PENDING):
        _sha(raw.get("expected_raw_tree_sha256"), "raw_binding.expected_raw_tree_sha256")
    mass = request.get("mass_semantics")
    if not isinstance(mass, Mapping) or mass.get("rigid_body_inference_from_particle_sum") is not False:
        raise FamilyNativeV2Error("rigid body mass must never be inferred from particle sums")
    for key in ("particle_mass_source", "support_weight_source", "rigid_body_mass_source"):
        if not isinstance(mass.get(key), str) or not mass[key]:
            raise FamilyNativeV2Error(f"mass_semantics.{key} is required")
    try:
        _v1._validate_xml_and_shape(request)
    except _v1.FamilyNativeError as error:
        raise FamilyNativeV2Error(str(error)) from error
    for item in request.get("source_files", []):
        if not isinstance(item, Mapping):
            raise FamilyNativeV2Error("source_files entry is malformed")
        _stat(item.get("path"), str(item.get("role")), expected_sha=item.get("sha256"), verify_hash=verify_sources and item.get("sha256") is not None)
    for role in ("decoder", "raw_converter"):
        item = request.get("decoder") if role == "decoder" else request.get("modules", {}).get("raw_converter")
        if not isinstance(item, Mapping):
            raise FamilyNativeV2Error(f"{role} binding is required")
        _stat(item.get("path"), role, expected_sha=item.get("sha256"), verify_hash=verify_sources)
    return {"family": family, "frames": int(expected["frames"]), "particles": int(expected["particles"]), "raw_root": root, "reference_hdf5": Path(str(h5["path"])).expanduser().resolve(), "expected_raw_tree": raw.get("expected_raw_tree_sha256")}


def prepare_report(request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load_json(request_file)
    bound = _validate_request(request, verify_sources=False)
    report = {
        "schema": REPORT_SCHEMA,
        "status": "READY_FOR_PARENT_IO_SLOT",
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "source_closure": {"family_id": bound["family"], "frames": bound["frames"], "particles": bound["particles"], "raw_root": str(bound["raw_root"]), "expected_raw_tree_sha256": bound["expected_raw_tree"], "expected_raw_tree_status": "UNKNOWN_PENDING_PARENT_WORKER" if bound["expected_raw_tree"] is None else "BOUND", "current_reference_shape_bound": True},
        "execution_boundary": {"raw_opened": False, "hdf5_opened": False, "converter_invoked": False, "family_labels_invoked": False, "model_invoked": False, "cfd_invoked": False, "parent_stage2guard_required": True},
        "typed_comparison": {"status": "PENDING_PARENT_IO_SLOT", "all_frames": True, "identity_key": "(Zone,Idp)", "lifecycle": "valid=false retains identity; state unknown"},
        "labels": {"status": "PENDING_FAMILY_SPECIFIC_OPERATOR", "f2_receiver_operator_invoked": False},
        "qualification": UNKNOWN,
    }
    report["report_sha256"] = canonical_sha(report)
    _write_new(output_path, report)
    return report


def run(request_path: Path | str, output_dir: Path | str, *, io_slot_approved: bool = False) -> dict[str, Any]:
    """Run metadata preflight; approved raw/HDF5 path delegates only at parent slot."""
    request_file = Path(request_path).expanduser().resolve()
    request = _load_json(request_file)
    bound = _validate_request(request, verify_sources=bool(io_slot_approved and not request.get("source_hashes_preverified_by_parent")))
    target = Path(output_dir).expanduser().resolve()
    if target.exists():
        raise FamilyNativeV2Error(f"refusing to use existing output directory: {target}")
    target.mkdir(parents=True, exist_ok=False)
    if not io_slot_approved:
        report = {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT", "request": {"path": str(request_file), "sha256": sha256_file(request_file)}, "execution_boundary": {"raw_opened": False, "hdf5_opened": False, "converter_invoked": False, "family_labels_invoked": False, "model_invoked": False, "cfd_invoked": False}, "source_closure": {"family_id": bound["family"], "frames": bound["frames"], "particles": bound["particles"], "expected_raw_tree_sha256": bound["expected_raw_tree"]}, "qualification": UNKNOWN}
        _write_new(target / "metadata-preflight.json", report)
        return report
    # The v2 request is intentionally source-compatible with the audited v1
    # converter path.  Delegate only after the caller explicitly grants I/O.
    converter = _v1._load_module(Path(str(request["modules"]["raw_converter"]["path"])), "_ds02_family_bound_converter_v2")
    generated_xml = Path(str(next(item for item in request["source_files"] if item.get("role") == "generated_xml")["path"]))
    solver_receipt = Path(str(next(item for item in request["source_files"] if item.get("role") == "solver_receipt")["path"]))
    gencase_receipt = Path(str(next(item for item in request["source_files"] if item.get("role") == "gencase_receipt")["path"]))
    owner = Path(str(next(item for item in request["source_files"] if item.get("role") == "owner_metadata")["path"]))
    run_out = Path(str(next(item for item in request["source_files"] if item.get("role") == "solver_run_out")["path"]))
    started = __import__("time").monotonic()
    typed_path = target / "typed-reconstructed.h5"
    converter_report_path = target / "raw-converter-report.json"
    converter_report = converter.convert_direct(data_root=bound["raw_root"], generated_xml=generated_xml, output=typed_path, report_path=converter_report_path, decoder=Path(str(request["decoder"]["path"])), partvtk=None, validation_dir=None, solver_log=run_out, solver_receipt=solver_receipt, gencase_receipt=gencase_receipt, owner_metadata=owner, reference_hdf5=bound["reference_hdf5"], run_partvtk=False, particle_chunk=65536)
    raw_tree = converter_report.get("source_provenance", {}).get("raw_tree", {})
    actual_before, actual_after = raw_tree.get("before_tree_sha256"), raw_tree.get("after_tree_sha256")
    if actual_before != actual_after or raw_tree.get("unchanged") is not True:
        raise FamilyNativeV2Error("raw source tree changed during conversion")
    expected_tree = bound["expected_raw_tree"]
    if expected_tree is not None and actual_before != expected_tree:
        raise FamilyNativeV2Error("raw source tree differs from declared producer digest")
    report = {"schema": REPORT_SCHEMA, "status": "COMPLETE_DEVELOPMENT_UNKNOWN", "request": {"path": str(request_file), "sha256": sha256_file(request_file)}, "source_closure": {"family_id": bound["family"], "frames": bound["frames"], "particles": bound["particles"], "raw_tree": {"expected": expected_tree, "actual_before": actual_before, "actual_after": actual_after, "expected_status": "UNKNOWN_UNTIL_WORKER" if expected_tree is None else "BOUND"}, "reference_hdf5": str(bound["reference_hdf5"])}, "raw_to_typed": {"status": "COMPLETE", "converter_report": str(converter_report_path), "converter_report_sha256": sha256_file(converter_report_path)}, "typed_output": {"path": str(typed_path), "bytes": typed_path.stat().st_size, "sha256": sha256_file(typed_path)}, "typed_full_current_compare": converter_report.get("reference_hdf5_comparison"), "labels": {"status": "PENDING_FAMILY_SPECIFIC_OPERATOR", "f2_receiver_operator_invoked": False}, "execution_boundary": {"raw_opened": True, "hdf5_opened": True, "converter_invoked": True, "family_labels_invoked": False, "model_invoked": False, "cfd_invoked": False, "parent_stage2guard_required": True}, "resource": {"wall_seconds": __import__("time").monotonic() - started}, "qualification": UNKNOWN}
    report["report_sha256"] = canonical_sha(report)
    _write_new(target / "raw-to-typed-compare-report.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    import argparse, json
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--anchor-plan", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--request", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
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
    except (FamilyNativeV2Error, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": result.get("schema", REQUEST_SCHEMA), "status": result.get("status"), "family_id": result.get("family_id"), "qualification": result.get("qualification", UNKNOWN)}, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
