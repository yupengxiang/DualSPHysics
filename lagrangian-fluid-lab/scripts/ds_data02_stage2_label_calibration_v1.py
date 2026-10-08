#!/usr/bin/env python3
"""Calibrate source labels and censoring fields from completed Stage2 evidence.

This is a small, no-model consumer of the completed all-118 native mechanism
report.  It reads only JSON, XML, and official source text that was already
registered by completed receipts.  It does not open H5/BI4/OBI4, invoke a
decoder or solver, or assign QN/QE, physical fate, legal flux, or dynamics.

``source_mk`` is resolved from the conversion report's typed initial block
ranges.  The scan's ``zone`` is retained as the historical ``(Zone,Idp)``
key component, but is never treated as an MK or as a material/region label.
The evaluator therefore distinguishes exact source-MK evidence from an
unknown destination material/region and from structural evidence errors.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Any


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
PRIMARY_LAB_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")

V2_REPORT_DEFAULT = DATA_ROOT / (
    "families/infra/STAGE2_OMISSION_MECHANISM_PROBE_ALL118_V2/"
    "omission-mechanism-probe-v2-primary-001-v8-root/omission-mechanism-probe-v2.json"
)
V2_RECEIPT_DEFAULT = V2_REPORT_DEFAULT.parent / "execution-receipt.json"
V2_MANIFEST_DEFAULT = PRIMARY_LAB_ROOT / (
    "campaigns/ds-data-02/stage2/requests/omission-mechanism-probe-v2/"
    "omission-mechanism-probe-v2-manifest.json"
)
V2_REQUEST_DEFAULT = PRIMARY_LAB_ROOT / (
    "campaigns/ds-data-02/stage2/requests/omission-mechanism-probe-v2/"
    "omission-mechanism-probe-v2-request.json"
)
CLOSURE_DEFAULT = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/evidence/"
    "f2-s1-native-source-closure-v1/f2-s1-native-source-closure.json"
)
CURRENT_DEFAULT = WORKTREE_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/CURRENT336.json"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"

F6_OUTPUT_DEFAULT = DATA_ROOT / (
    "families/F6/STAGE2_F6_STATIC_KABSCH_COMBINED_V5/"
    "f6-static-kabsch-combined-v5-primary-001/f6-static-kabsch-combined.json"
)
F6_RECEIPT_DEFAULT = F6_OUTPUT_DEFAULT.parent / "execution-receipt.json"
F6_BUNDLE_DEFAULT = PRIMARY_LAB_ROOT / (
    "campaigns/ds-data-02/stage2/requests/"
    "f6-static-kabsch-combined-v5-root-bundle-001.json"
)

OFFICIAL_FILES_DEFAULT = (
    WORKTREE_ROOT / "src/source/DualSphDef.h",
    WORKTREE_ROOT / "src/source/JSph.cpp",
    WORKTREE_ROOT / "src/source/JCaseParts.cpp",
    WORKTREE_ROOT / "src/source/JSphMk.cpp",
    WORKTREE_ROOT / "src/source/JPartFloatInfoBi4.cpp",
    WORKTREE_ROOT / "src/source/JPartFloatInfoBi4.h",
    WORKTREE_ROOT / "doc/help/FloatingInfo_Help.out",
)

OUTPUT_SCHEMA = "ds02.stage2.label-calibration.v1"
REQUEST_SCHEMA = "ds02.request.v1"
V2_SCHEMA = "ds02.stage2.omission-mechanism-probe.v2"
V2_STATUS = "MECHANISM_PROBE_SOURCE_CLOSED_NO_H5"
F6_OUTPUT_SCHEMA = "ds02.stage2.f6-static-kabsch-combined.v5"
F6_BUNDLE_SCHEMA = "ds02.stage2.f6-static-kabsch-combined-bundle.v5"
FAMILY_COUNTS = {"F2": 48, "F4": 22, "F6": 48}
MASS_GATE = 0.003
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".obi4", ".bi4"}
F2_S1_KEY = "F2/scan-F2-S1-001"


class LabelCalibrationError(RuntimeError):
    """Raised when a completed small-source binding is not exact."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def forbidden(path: Path) -> bool:
    return path.suffix.lower() in FORBIDDEN_SUFFIXES or (
        path.name.startswith("Part_") and path.suffix.lower() == ".bi4"
    )


def require_file(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise LabelCalibrationError(f"{label} is missing: {path}")
    if forbidden(path):
        raise LabelCalibrationError(f"raw H5/BI4/OBI4 input is forbidden: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LabelCalibrationError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise LabelCalibrationError(f"{label} is not a JSON object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    if path.exists():
        raise LabelCalibrationError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def binding(path: Path | str, label: str, expected: str | None = None) -> dict[str, Any]:
    path = require_file(path, label)
    digest = sha256(path)
    if expected is not None and digest != expected:
        raise LabelCalibrationError(f"{label} digest differs: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest}


def get_path_binding(item: Any, label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
        raise LabelCalibrationError(f"{label} lacks path/sha256 binding")
    path = require_file(item["path"], label)
    digest = sha256(path)
    if digest != item["sha256"]:
        raise LabelCalibrationError(f"{label} digest differs: {path}")
    declared_bytes = item.get("bytes")
    if declared_bytes is not None and int(declared_bytes) != path.stat().st_size:
        raise LabelCalibrationError(f"{label} byte count differs: {path}")
    return path, {"path": str(path), "bytes": path.stat().st_size, "sha256": digest}


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def validate_v2(report_path: Path, receipt_path: Path, manifest_path: Path,
                request_path: Path, current_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    report_path, report = read_json(report_path, "completed v2 mechanism report")
    receipt_path, receipt = read_json(receipt_path, "completed v2 mechanism receipt")
    manifest_path, manifest = read_json(manifest_path, "v2 mechanism manifest")
    request_path, request = read_json(request_path, "v2 mechanism request")
    current = binding(current_path, "CURRENT336 identity", CURRENT_SHA256)
    if report.get("schema") != V2_SCHEMA or report.get("status") != V2_STATUS:
        raise LabelCalibrationError("v2 report schema/status differs")
    if request.get("schema") != REQUEST_SCHEMA or request.get("case_id") != "STAGE2_OMISSION_MECHANISM_PROBE_ALL118_V2":
        raise LabelCalibrationError("v2 request identity differs")
    if manifest.get("schema") != "ds02.stage2.omission-mechanism-probe-manifest.v2":
        raise LabelCalibrationError("v2 manifest schema differs")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise LabelCalibrationError("v2 receipt is not completed code 0")
    if receipt.get("input_hashes_at_launch") != receipt.get("input_hashes_after_run"):
        raise LabelCalibrationError("v2 receipt input hashes are not stable")
    receipt_request = receipt.get("request", {})
    if receipt_request.get("case_id") != request.get("case_id"):
        raise LabelCalibrationError("v2 receipt request identity differs")
    request_hashes = receipt_request.get("input_sha256")
    request_files = receipt_request.get("input_files")
    launch_hashes = receipt.get("input_hashes_at_launch")
    end_hashes = receipt.get("input_hashes_after_run")
    if not isinstance(request_hashes, dict) or not isinstance(request_files, list):
        raise LabelCalibrationError("v2 receipt request lacks exact input hash map")
    if set(request_files) != set(request_hashes):
        raise LabelCalibrationError("v2 receipt request input file/hash sets differ")
    if launch_hashes != request_hashes or end_hashes != request_hashes:
        raise LabelCalibrationError("v2 receipt launch/end input hashes differ from its completed request")
    # A guarded forward request may embed the canonical request while retaining
    # the original request/manifest paths.  Bind those original files by the
    # explicit forward-root hashes; do not silently assume the mutable path's
    # current bytes are the canonical wrapper request.
    request_binding = binding(request_path, "v2 request")
    manifest_binding = binding(manifest_path, "v2 manifest")
    forward = receipt_request.get("forward_root_binding")
    if isinstance(forward, dict):
        if forward.get("original_request") != request_binding["path"] or forward.get("original_request_sha256") != request_binding["sha256"]:
            raise LabelCalibrationError("v2 forward receipt does not bind the supplied original request")
        if forward.get("source_manifest_sha256") != manifest_binding["sha256"]:
            raise LabelCalibrationError("v2 forward receipt does not bind the supplied manifest")
    elif receipt.get("request_sha256") != request_binding["sha256"]:
        raise LabelCalibrationError("v2 receipt request SHA is not the supplied request")
    if len(report.get("cases", [])) != 118 or report.get("coverage", {}).get("selected_case_counts") != FAMILY_COUNTS:
        raise LabelCalibrationError("v2 report coverage differs")
    if report.get("coverage", {}).get("selected_native_id_count") != 1328:
        raise LabelCalibrationError("v2 native ID count differs")
    for name in ("h5_opened", "trajectory_content_opened", "raw_partout_opened", "decoder_started", "solver_started", "cfd_or_model_run"):
        if report.get("read_policy", {}).get(name) is not False:
            raise LabelCalibrationError(f"v2 read policy is not closed: {name}")
    return report, receipt, {
        "report": binding(report_path, "v2 report"),
        "receipt": binding(receipt_path, "v2 receipt"),
        "manifest": binding(manifest_path, "v2 manifest"),
        "request": binding(request_path, "v2 request"),
        "current": current,
    }


def validate_completed_receipt(item: Any, label: str, expected_output_root: Path | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate a producer receipt without opening its scientific payloads."""
    errors: list[str] = []
    try:
        receipt_path, _ = get_path_binding(item, label)
        receipt = read_json(receipt_path, label)[1]
    except LabelCalibrationError as exc:
        return None, [str(exc)]
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        errors.append(f"{label}_schema_mismatch")
    if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        errors.append(f"{label}_not_completed_code_0")
    launch = receipt.get("input_hashes_at_launch")
    after = receipt.get("input_hashes_after_run")
    if not isinstance(launch, dict) or not isinstance(after, dict) or launch != after:
        errors.append(f"{label}_input_hashes_not_stable")
    request = receipt.get("request")
    if not isinstance(request, dict) or not isinstance(request.get("input_sha256"), dict) or not isinstance(launch, dict):
        errors.append(f"{label}_request_input_hashes_not_bound")
    else:
        requested = request["input_sha256"]
        missing = set(requested) - set(launch)
        extra = set(launch) - set(requested)
        interpreter_path = lambda value: Path(value).name.startswith("python") or str(value).endswith("/bin/python")
        if missing and not all(interpreter_path(value) for value in missing):
            errors.append(f"{label}_request_input_hashes_not_bound")
        # The v8 runner records its normalized interpreter as an additional
        # input after request construction.  It is a source identity check,
        # not an unbound scientific input.  Any other extra is rejected.
        if extra and not all(interpreter_path(value) for value in extra):
            errors.append(f"{label}_unexpected_runner_inputs")
    if expected_output_root is not None:
        declared = receipt.get("output_root")
        if not declared or Path(declared).expanduser().resolve() != expected_output_root.expanduser().resolve():
            errors.append(f"{label}_output_root_mismatch")
    return receipt, errors


def validate_scan(case: dict[str, Any], closure: dict[str, Any] | None = None) -> tuple[Path, dict[str, Any], list[str]]:
    source_files = case.get("source_files", {})
    # The historical three-particle F2-S1 case predates the all-118 report's
    # per-case decoder/solver aliases.  Its exact source-closure sidecar is a
    # producer-bound substitute; do not silently join a neighboring run.
    if case.get("case_key") == F2_S1_KEY and closure is not None:
        closure_bindings = closure.get("source_bindings", {})
        source_files = dict(source_files)
        for role, closure_name in (
            ("native_csv", "old_partvtkout_csv"),
            ("decoder_receipt", "old_partvtkout_receipt"),
            ("run_out", "runout"),
            ("runparts", "runparts"),
            ("solver_receipt", "solver_receipt"),
        ):
            if role not in source_files and isinstance(closure_bindings.get(closure_name), dict):
                source_files[role] = closure_bindings[closure_name]
    scan_path, scan_binding = get_path_binding(source_files.get("scan"), f"{case.get('case_key')} scan")
    scan = read_json(scan_path, "scientific scan")[1]
    errors: list[str] = []
    if scan.get("scan_status") != "SCANNED":
        errors.append("scan_not_SCANNED")
    if scan.get("failures"):
        errors.append("scan_field_failures_present")
    if scan.get("family_id") != case.get("family_id"):
        errors.append("scan_family_identity_mismatch")
    if scan.get("physical_case_id") != case.get("physical_case_id"):
        errors.append("scan_physical_case_identity_mismatch")
    ledgers = scan.get("type_ledgers", {})
    fluid = ledgers.get("fluid", {})
    if fluid.get("type_code") != 3:
        errors.append("scan_fluid_type_code_not_3")
    if not finite_number(fluid.get("typed_initial_mass_kg")):
        errors.append("scan_fluid_initial_mass_missing")
    if not isinstance(scan.get("missing_id_records"), list):
        errors.append("scan_missing_id_records_not_list")
    # The v2 report's native motive is credited only when its producer
    # receipts are still completed and point to the exact small outputs used
    # by the report.  This checks JSON receipt metadata only; it never reads
    # the trajectory, BI4/OBI4, or a decoder input.
    native_csv_item = source_files.get("native_csv")
    run_out_item = source_files.get("run_out")
    try:
        native_csv_path, _ = get_path_binding(native_csv_item, f"{case.get('case_key')} native CSV")
        run_out_path, _ = get_path_binding(run_out_item, f"{case.get('case_key')} Run.out")
    except LabelCalibrationError as exc:
        errors.append(str(exc))
        native_csv_path = run_out_path = None
    receipt_specs = (
        ("scan_receipt", scan_path.parent),
        ("decoder_receipt", native_csv_path.parent if native_csv_path is not None else None),
        ("solver_receipt", run_out_path.parent.parent if run_out_path is not None else None),
    )
    for role, expected_root in receipt_specs:
        if expected_root is None:
            errors.append(f"{case.get('case_key')}_{role}_output_root_unavailable")
            continue
        _, receipt_errors = validate_completed_receipt(source_files.get(role), f"{case.get('case_key')} {role}", expected_root)
        errors.extend(receipt_errors)
    return scan_path, scan, errors


def conversion_for_case(case: dict[str, Any], closure: dict[str, Any] | None) -> tuple[Path | None, dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    source_files = case.get("source_files", {})
    item = source_files.get("conversion_report")
    if item is None and case.get("case_key") == F2_S1_KEY and closure is not None:
        item = closure.get("source_bindings", {}).get("current_conversion_report")
    if item is None:
        return None, None, ["conversion_report_binding_missing"]
    try:
        path, _ = get_path_binding(item, f"{case.get('case_key')} conversion report")
        payload = read_json(path, "conversion report")[1]
    except LabelCalibrationError as exc:
        return None, None, [str(exc)]
    if payload.get("conversion_status") != "completed":
        errors.append("conversion_not_completed")
    identity = payload.get("typed_identity", {})
    if identity.get("key") != "(Zone,Idp)":
        errors.append("conversion_identity_key_missing")
    if not isinstance(identity.get("blocks"), list):
        errors.append("conversion_typed_blocks_missing")
    return path, payload, errors


def source_mk_match(idp: int, type_code: int, zone: Any, conversion: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve the absolute source MK from typed initial ID ranges.

    ``zone`` is returned for audit context only.  It is deliberately not used
    to infer ``mk`` or a material/region destination.
    """
    result: dict[str, Any] = {
        "idp": idp,
        "legacy_zone": zone,
        "legacy_zone_semantics": "BI4 Piece component of (Zone,Idp), not an MK/material/region label",
        "source_mk": None,
        "source_mkfluid": None,
        "source_type_code": None,
        "status": "UNKNOWN_SOURCE_MK_MAPPING",
        "mapping_source": None,
    }
    if not isinstance(zone, int) or isinstance(zone, bool):
        result["status"] = "ERROR_SOURCE_MK_MAPPING"
        result["error"] = "zone_key_not_integer"
        return result
    if conversion is None:
        result["error"] = "conversion_report_unavailable"
        return result
    identity = conversion.get("typed_identity", {})
    blocks = identity.get("blocks")
    if not isinstance(blocks, list):
        result["error"] = "typed_blocks_unavailable"
        return result
    candidates = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != type_code:
            continue
        begin, count = block.get("begin"), block.get("count")
        if isinstance(begin, int) and isinstance(count, int) and count > 0 and begin <= idp < begin + count:
            candidates.append(block)
    if len(candidates) != 1:
        result["status"] = "ERROR_SOURCE_MK_MAPPING" if len(candidates) > 1 else "UNKNOWN_SOURCE_MK_MAPPING"
        result["error"] = "ambiguous_typed_block_range" if len(candidates) > 1 else "id_outside_typed_block_ranges"
        return result
    block = candidates[0]
    if block.get("tag") != "fluid" or block.get("mk") is None or block.get("mkfluid") is None:
        result["status"] = "ERROR_SOURCE_MK_MAPPING"
        result["error"] = "matched_block_not_complete_fluid_source"
        return result
    result.update({
        "source_mk": block["mk"],
        "source_mkfluid": block["mkfluid"],
        "source_type_code": block.get("type"),
        "source_block_begin": block["begin"],
        "source_block_count": block["count"],
        "status": "VALID_SOURCE_MK_MAPPING",
    })
    return result


def enrich_f2_s1_observations(observations: list[dict[str, Any]], reconciliation: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Attach the exact small F2-S1 pre-gap kinematics to old observations.

    The all-118 report deliberately preserved the historical three-ID ledger
    without RunPARTs/CSV fields.  The separate source-closure reconciliation
    contains the last known saved time, velocity, and native endpoint.  This
    enrichment names the saved time correctly and never treats it as the
    physical deletion time.
    """
    if not reconciliation:
        return observations
    by_id = {
        row.get("idp"): row
        for row in reconciliation.get("missing_fluid_ids", [])
        if isinstance(row, dict) and isinstance(row.get("idp"), int)
    }
    enriched: list[dict[str, Any]] = []
    for original in observations:
        obs = copy.deepcopy(original)
        row = by_id.get(obs.get("idp"))
        previous = row.get("first_gap_previous_state", {}) if isinstance(row, dict) else {}
        mass = row.get("initial_mass_kg") if isinstance(row, dict) else obs.get("mass_kg")
        velocity = previous.get("velocity_m_s") if isinstance(previous, dict) else None
        if (
            isinstance(velocity, list)
            and len(velocity) == 3
            and all(finite_number(value) for value in velocity)
            and finite_number(mass)
        ):
            mass_float = float(mass)
            velocity_float = [float(value) for value in velocity]
            obs["saved_record_time_s"] = previous.get("time_s")
            obs["saved_record_velocity_m_s"] = velocity_float
            obs["momentum_kg_m_s"] = [mass_float * value for value in velocity_float]
            obs["kinetic_energy_j"] = 0.5 * mass_float * sum(value * value for value in velocity_float)
            obs["saved_record_time_semantics"] = "last_known_pre_gap_saved_time; not exact physical deletion time"
            obs["kinematic_source"] = "F2-S1 native source-closure first_gap_previous_state"
        if isinstance(row, dict):
            native_record = row.get("native_record", {})
            if isinstance(native_record, dict):
                if isinstance(native_record.get("position_m"), list):
                    obs["endpoint_position_m"] = native_record["position_m"]
                if finite_number(native_record.get("density_kg_m3")):
                    obs["endpoint_density_kg_m3"] = native_record["density_kg_m3"]
        enriched.append(obs)
    return enriched


def particle_label(case: dict[str, Any], scan: dict[str, Any], conversion: dict[str, Any] | None,
                   reconciliation: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    observations = case.get("particle_observations")
    if not isinstance(observations, list):
        return [], ["native_particle_observations_missing"]
    observations = enrich_f2_s1_observations(observations, reconciliation)
    records = [r for r in scan.get("missing_id_records", []) if isinstance(r, dict) and r.get("type_code") == 3]
    by_id: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        if isinstance(record.get("idp"), int):
            by_id.setdefault(record["idp"], []).append(record)
    labels: list[dict[str, Any]] = []
    for obs in observations:
        idp = obs.get("idp")
        row_errors: list[str] = []
        matches = by_id.get(idp, []) if isinstance(idp, int) else []
        if len(matches) != 1:
            row_errors.append("missing_or_ambiguous_typed_fluid_identity")
            record: dict[str, Any] = {}
        else:
            record = matches[0]
        type_code = record.get("type_code", obs.get("native_type_code", 3))
        mk = source_mk_match(idp, type_code, record.get("zone"), conversion) if isinstance(idp, int) else {
            "status": "ERROR_SOURCE_MK_MAPPING", "error": "idp_not_integer"
        }
        if len(matches) == 1 and record.get("first_missing_frame") is not None and obs.get("saved_record_time_s") is None:
            row_errors.append("missing_saved_record_time")
        bracket = obs.get("saved_record_bracket_s") or obs.get("first_missing_bracket_s")
        bracket_valid = (
            isinstance(bracket, list) and len(bracket) == 2 and all(finite_number(x) for x in bracket)
            and float(bracket[0]) <= float(bracket[1])
        )
        if not bracket_valid:
            row_errors.append("saved_record_bracket_missing_or_invalid")
        labels.append({
            "idp": idp,
            "native_motive": obs.get("native_motive"),
            "native_motive_code": obs.get("native_motive_code"),
            "source_mk_mapping": mk,
            "typed_record": {
                "type_code": record.get("type_code"),
                "zone": record.get("zone"),
                "initial_mass_kg": record.get("initial_mass_kg"),
                "first_missing_frame": record.get("first_missing_frame"),
            },
            "censoring": {
                "saved_record_bracket_s": bracket if bracket_valid else None,
                "saved_record_time_s": obs.get("saved_record_time_s"),
                "saved_record_time_semantics": obs.get("saved_record_time_semantics", "saved native record time; exact physical event time UNKNOWN"),
                "exact_physical_event_time": "UNKNOWN",
                "reentry_or_repeated_crossing": "UNKNOWN",
                "signed_net_flux": "UNKNOWN",
            },
            "saved_record_kinematics": {
                "velocity_m_s": obs.get("saved_record_velocity_m_s"),
                "momentum_kg_m_s": obs.get("momentum_kg_m_s"),
                "kinetic_energy_j": obs.get("kinetic_energy_j"),
                "aggregation": "per-particle saved-record observation; no cross-time system sum",
                "physical_event_time": "UNKNOWN",
            },
            "labels": {
                "native_cause": "VALID_NATIVE_CAUSE" if not row_errors and obs.get("native_motive") in {"position", "density", "movement"} else "ERROR_NATIVE_CAUSE",
                "source_mk": mk.get("status", "UNKNOWN_SOURCE_MK_MAPPING"),
                "saved_record_bracket": "VALID_SAVED_RECORD_BRACKET" if bracket_valid else "ERROR_SAVED_RECORD_BRACKET",
                "material_region_destination": "UNKNOWN_DESTINATION_MATERIAL_REGION",
                "physical_fate": "UNKNOWN_PHYSICAL_FATE",
                "dynamical_impact": "UNKNOWN_DYNAMICAL_IMPACT",
            },
            "errors": row_errors,
        })
    if len(records) != len(observations):
        errors.append("typed_fluid_count_native_observation_count_mismatch")
    return labels, errors


def case_label(case: dict[str, Any], scan: dict[str, Any], conversion: dict[str, Any] | None,
               conversion_errors: list[str], scan_errors: list[str],
               reconciliation: dict[str, Any] | None = None) -> dict[str, Any]:
    labels, join_errors = particle_label(case, scan, conversion, reconciliation)
    errors = list(scan_errors) + list(conversion_errors) + list(join_errors)
    native = case.get("native_gate", {})
    native_count = int(native.get("native_count", len(labels))) if isinstance(native.get("native_count", len(labels)), int) else len(labels)
    if native_count != len(labels):
        errors.append("native_gate_count_observation_count_mismatch")
    mapping_statuses = [x.get("source_mk_mapping", {}).get("status") for x in labels]
    bracket_valid = sum(x.get("labels", {}).get("saved_record_bracket") == "VALID_SAVED_RECORD_BRACKET" for x in labels)
    source_valid = sum(x == "VALID_SOURCE_MK_MAPPING" for x in mapping_statuses)
    source_error = sum(x == "ERROR_SOURCE_MK_MAPPING" for x in mapping_statuses)
    source_unknown = sum(x == "UNKNOWN_SOURCE_MK_MAPPING" for x in mapping_statuses)
    ledger = scan.get("type_ledgers", {}).get("fluid", {})
    lifecycle = {
        "revived_unique_ids": ledger.get("revived_unique_ids", "UNKNOWN"),
        "births_unique_ids": ledger.get("births_unique_ids", "UNKNOWN"),
        "initially_absent_count": ledger.get("initially_absent_count", "UNKNOWN"),
        "first_arrival": "UNKNOWN",
        "residence_time": "UNKNOWN",
        "reentry_or_repeated_crossing": "UNKNOWN",
        "signed_net_flux": "UNKNOWN",
        "interpretation": "lifecycle/re-entry semantics do not follow from first missing saved record",
    }
    mass_visibility = case.get("mass_visibility", {})
    initial_mass = ledger.get("typed_initial_mass_kg")
    mass_fraction = mass_visibility.get("missing_source_visible_fraction_lower_bound")
    if finite_number(initial_mass) and finite_number(mass_visibility.get("missing_source_visible_mass_lower_bound_kg")) and float(initial_mass) > 0:
        mass_fraction_recomputed = float(mass_visibility["missing_source_visible_mass_lower_bound_kg"]) / float(initial_mass)
    else:
        mass_fraction_recomputed = None
        errors.append("mass_screen_denominator_missing")
    if mass_fraction is not None and mass_fraction_recomputed is not None and abs(float(mass_fraction) - mass_fraction_recomputed) > 1e-9:
        errors.append("mass_screen_fraction_mismatch")
    source_mk_cohorts: dict[str, dict[str, Any]] = {}
    for label in labels:
        mapping = label.get("source_mk_mapping", {})
        if mapping.get("status") != "VALID_SOURCE_MK_MAPPING":
            continue
        cohort_key = f"mk{mapping['source_mk']}/mkfluid{mapping['source_mkfluid']}"
        cohort = source_mk_cohorts.setdefault(cohort_key, {
            "source_mk": mapping["source_mk"],
            "source_mkfluid": mapping["source_mkfluid"],
            "typed_block_begin": mapping.get("source_block_begin"),
            "typed_block_count": mapping.get("source_block_count"),
            "missing_particle_count": 0,
            "missing_source_visible_mass_kg": 0.0,
            "native_motive_counts": {},
            "first_missing_brackets_s": [],
            "source_mk_initial_mass_denominator_kg": None,
            "source_mk_mass_fraction": "UNKNOWN_PER_MK_INITIAL_ARRAY_NOT_READ",
            "first_arrival": "UNKNOWN",
            "residence_time": "UNKNOWN",
            "repeated_crossing": "UNKNOWN",
            "signed_net_flux": "UNKNOWN",
            "destination_material_region": "UNKNOWN",
            "physical_fate": "UNKNOWN",
        })
        cohort["missing_particle_count"] += 1
        mass = label.get("typed_record", {}).get("initial_mass_kg")
        if finite_number(mass):
            cohort["missing_source_visible_mass_kg"] += float(mass)
        motive = label.get("native_motive") or "UNKNOWN"
        motive_counts = cohort["native_motive_counts"]
        motive_counts[motive] = motive_counts.get(motive, 0) + 1
        bracket = label.get("censoring", {}).get("saved_record_bracket_s")
        if isinstance(bracket, list):
            cohort["first_missing_brackets_s"].append(bracket)
    for cohort in source_mk_cohorts.values():
        cohort["missing_source_visible_mass_kg"] = round(cohort["missing_source_visible_mass_kg"], 15)
    if errors:
        structural = "ERROR_LABEL_EVIDENCE"
    elif source_error:
        structural = "ERROR_LABEL_EVIDENCE"
    elif source_unknown:
        structural = "UNKNOWN_LABEL_EVIDENCE"
    else:
        structural = "VALID_LABEL_EVIDENCE"
    # This label is deliberately about source-label evidence only.  It never
    # turns the physical-fate/dynamics unknowns into a pass or QN credit.
    return {
        "case_key": case.get("case_key"),
        "family_id": case.get("family_id"),
        "physical_case_id": case.get("physical_case_id"),
        "structural_label_status": structural,
        "native_motive": native.get("motive"),
        "native_count": native_count,
        "source_mk_counts": {"valid": source_valid, "error": source_error, "unknown": source_unknown},
        "source_mk_cohorts": source_mk_cohorts,
        "saved_record_bracket_count": bracket_valid,
        "saved_record_bracket_status": "VALID_SAVED_RECORD_BRACKET" if bracket_valid == len(labels) else ("UNKNOWN_SAVED_RECORD_BRACKET" if bracket_valid == 0 else "PARTIAL_SAVED_RECORD_BRACKET"),
        "first_missing_window_s": case.get("first_missing_window_s"),
        "censoring": lifecycle,
        "source_semantic_enrichment": {
            "status": "F2_S1_CLOSURE_KINEMATICS_BOUND" if reconciliation is not None else "NOT_APPLICABLE",
            "saved_record_velocity_momentum_ke": "bound from first_gap_previous_state" if reconciliation is not None else "from completed v2 observation if present",
            "physical_event_time": "UNKNOWN",
            "cross_time_system_aggregation": "FORBIDDEN_AS_DYNAMICS_ESTIMATE",
        },
        "mass_screen": {
            "frozen_gate_fraction": MASS_GATE,
            "initial_fluid_mass_denominator_kg": initial_mass,
            "missing_source_visible_mass_lower_bound_kg": mass_visibility.get("missing_source_visible_mass_lower_bound_kg"),
            "missing_source_visible_fraction_lower_bound": mass_fraction,
            "recomputed_fraction_from_scan_mass": mass_fraction_recomputed,
            "screen_only": True,
            "dynamics_credit": "NONE",
        },
        "region_material": {
            "source_mk_is_observed": source_valid == len(labels) and not source_error,
            "destination_material_region": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
        },
        "labels": {
            "native_cause": "VALID_NATIVE_CAUSE" if not errors else "ERROR_OR_UNKNOWN_NATIVE_EVIDENCE",
            "source_mk": "VALID_SOURCE_MK_MAPPING" if source_valid == len(labels) else ("ERROR_SOURCE_MK_MAPPING" if source_error else "UNKNOWN_SOURCE_MK_MAPPING"),
            "material_region_destination": "UNKNOWN_DESTINATION_MATERIAL_REGION",
            "physical_fate": "UNKNOWN_PHYSICAL_FATE",
            "dynamical_impact": "UNKNOWN_DYNAMICAL_IMPACT",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        },
        "errors": sorted(set(errors)),
        "particle_labels": labels,
    }


def source_line(path: Path, terms: tuple[str, ...]) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    matches = []
    for number, line in enumerate(lines, 1):
        if any(term in line for term in terms):
            matches.append({"line": number, "text": line.strip()[:240]})
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "matches": matches[:12]}


def xml_frozen_geometry(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    floating_nodes = []
    for node in root.iter():
        if node.tag.lower() == "floating":
            floating_nodes.append(dict(node.attrib))
    massbody = []
    masspart = []
    centers = []
    for node in root.iter():
        tag = node.tag.lower()
        if tag == "massbody":
            massbody.append(node.attrib.get("value"))
        elif tag == "masspart":
            masspart.append(node.attrib.get("value"))
        elif tag == "center":
            if all(k in node.attrib for k in ("x", "y", "z")):
                centers.append([float(node.attrib["x"]), float(node.attrib["y"]), float(node.attrib["z"])])
    return {
        "binding": binding(path, "frozen F6 generated XML"),
        "floating_nodes": floating_nodes,
        "massbody_values_kg": [float(x) for x in massbody if x is not None],
        "masspart_values_kg": [float(x) for x in masspart if x is not None],
        "center_values_m": centers,
        "initial_orientation_xml_field": "absent; solver initializes StFloatingData.angles to zero",
    }


def floating_semantics(f6_output_path: Path, f6_receipt_path: Path, f6_bundle_path: Path,
                       official_paths: list[Path]) -> dict[str, Any]:
    output_path, output = read_json(f6_output_path, "completed F6 Kabsch output")
    receipt_path, receipt = read_json(f6_receipt_path, "completed F6 Kabsch receipt")
    bundle_path, bundle = read_json(f6_bundle_path, "F6 Kabsch source bundle")
    if output.get("schema") != F6_OUTPUT_SCHEMA or output.get("status") != "completed":
        raise LabelCalibrationError("F6 Kabsch output schema/status differs")
    if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise LabelCalibrationError("F6 Kabsch receipt is not completed code 0")
    if bundle.get("schema") != F6_BUNDLE_SCHEMA:
        raise LabelCalibrationError("F6 source bundle schema differs")
    files = {"output": binding(output_path, "F6 Kabsch output"), "receipt": binding(receipt_path, "F6 Kabsch receipt"), "bundle": binding(bundle_path, "F6 Kabsch source bundle")}
    official = []
    for path in official_paths:
        official.append(source_line(path, ("StFloatingData", "fobj->center", "fobj->angles", "fobj->fomega", "CreateArray(\"center\"", "CreateArray(\"fomega\"", "Massbody", "GetMkBlockById", "GetMkById")))
    case_rows = []
    bundle_rows = {row.get("physical_case_id"): row for row in bundle.get("source_cases", []) if isinstance(row, dict)}
    for row in output.get("cases", []):
        case_id = row.get("physical_case_id")
        source = bundle_rows.get(case_id)
        if not source:
            raise LabelCalibrationError(f"F6 bundle lacks case {case_id}")
        small = source.get("small_sources", {})
        xml_item = small.get("generated_xml_path")
        xml_path, _ = get_path_binding(xml_item, f"{case_id} generated XML")
        xml = xml_frozen_geometry(xml_path)
        frozen = row.get("kabsch", {}).get("frozen_contract", {})
        case_rows.append({
            "sentinel_id": row.get("sentinel_id"),
            "physical_case_id": case_id,
            "generated_xml": xml,
            "official_solver_observation": {
                "center_field": "StFloatingData.center",
                "center_units": "m",
                "angular_velocity_field": "StFloatingData.fomega",
                "angular_velocity_units": "rad/s",
                "center_frame": frozen.get("observer_center_frame", "UNKNOWN"),
                "angular_velocity_frame": frozen.get("observer_angular_velocity_frame", "UNKNOWN"),
                "physical_COM_equivalence": "UNKNOWN",
                "euler_order_and_active_passive_csv_semantics": "UNKNOWN; FloatingInfo output stores center/fvel/fomega arrays, not an Euler-order declaration",
                "initial_rotation_state": "solver source initializes angles to zero; world-frame interpretation of downstream Kabsch remains UNKNOWN",
            },
            "mass_separation": {
                "physical_body_mass_kg": frozen.get("body_mass_kg", 128.0),
                "sampled_support_mass_kg": frozen.get("support_sample_mass_kg", row.get("kabsch", {}).get("support_sample_mass_kg")),
                "interaction_mass_semantics": "distinct quantities; no rescaling or dynamics credit",
            },
            "algebraic_kabsch_only": {
                "status": row.get("kabsch", {}).get("status"),
                "rotation_convention": frozen.get("rotation_convention"),
                "so3_error_tolerances_deg": frozen.get("so3_error_tolerances_deg"),
                "truth_qualification": "UNKNOWN",
            },
        })
    return {
        "schema": "ds02.stage2.f6-floatinginfo-semantics.v1",
        "official_source_bindings": official,
        "source_bindings": files,
        "cases": case_rows,
        "claim_boundary": {
            "physical_COM": "UNKNOWN",
            "observer_center_frame": "UNKNOWN",
            "observer_angular_velocity_frame": "UNKNOWN",
            "Euler_order_active_passive": "UNKNOWN",
            "SO3_truth": "UNKNOWN; direct proper Kabsch diagnostic only",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        },
        "read_policy": {"h5_opened_by_this_consumer": False, "bi4_opened_by_this_consumer": False, "decoder_started": False, "solver_started": False, "model_run": False},
    }


def audit(v2_report_path: Path, v2_receipt_path: Path, v2_manifest_path: Path, v2_request_path: Path,
          closure_path: Path, current_path: Path, f6_output_path: Path, f6_receipt_path: Path,
          f6_bundle_path: Path, official_paths: list[Path], output_path: Path) -> dict[str, Any]:
    report, receipt, base = validate_v2(v2_report_path, v2_receipt_path, v2_manifest_path, v2_request_path, current_path)
    closure = read_json(closure_path, "F2-S1 exact source closure")[1]
    if closure.get("schema") != "ds02.stage2.f2-s1-native-source-closure.v1" or closure.get("status") != "EXACT_NATIVE_SOURCE_CLOSED_WITH_PHYSICAL_FATE_UNKNOWN":
        raise LabelCalibrationError("F2-S1 closure schema/status differs")
    f2_s1_reconciliation = load_f2_s1_reconciliation(closure)
    cases = []
    status_counts = {"VALID_LABEL_EVIDENCE": 0, "ERROR_LABEL_EVIDENCE": 0, "UNKNOWN_LABEL_EVIDENCE": 0}
    family_status: dict[str, dict[str, int]] = {family: {key: 0 for key in status_counts} for family in FAMILY_COUNTS}
    for case in report["cases"]:
        _, scan, scan_errors = validate_scan(case, closure)
        _, conversion, conversion_errors = conversion_for_case(case, closure)
        reconciliation = f2_s1_reconciliation if case.get("case_key") == F2_S1_KEY else None
        row = case_label(case, scan, conversion, conversion_errors, scan_errors, reconciliation)
        cases.append(row)
        status_counts[row["structural_label_status"]] += 1
        family_status[row["family_id"]][row["structural_label_status"]] += 1
    source_mk_summary: dict[str, dict[str, Any]] = {}
    for row in cases:
        for cohort_key, cohort in row.get("source_mk_cohorts", {}).items():
            summary_key = f"{row['family_id']}/{cohort_key}"
            summary = source_mk_summary.setdefault(summary_key, {
                "family_id": row["family_id"],
                "source_mk": cohort["source_mk"],
                "source_mkfluid": cohort["source_mkfluid"],
                "case_count": 0,
                "missing_particle_count": 0,
                "missing_source_visible_mass_kg": 0.0,
                "native_motive_counts": {},
                "source_mk_initial_mass_denominator": "UNKNOWN_PER_MK_INITIAL_ARRAY_NOT_READ",
                "first_arrival": "UNKNOWN",
                "residence_time": "UNKNOWN",
                "repeated_crossing": "UNKNOWN",
                "signed_net_flux": "UNKNOWN",
                "destination_material_region": "UNKNOWN",
                "physical_fate": "UNKNOWN",
            })
            summary["case_count"] += 1
            summary["missing_particle_count"] += cohort["missing_particle_count"]
            summary["missing_source_visible_mass_kg"] += cohort["missing_source_visible_mass_kg"]
            for motive, count in cohort["native_motive_counts"].items():
                summary["native_motive_counts"][motive] = summary["native_motive_counts"].get(motive, 0) + count
    for summary in source_mk_summary.values():
        summary["missing_source_visible_mass_kg"] = round(summary["missing_source_visible_mass_kg"], 15)
    semantics = floating_semantics(f6_output_path, f6_receipt_path, f6_bundle_path, official_paths)
    return {
        "schema": OUTPUT_SCHEMA,
        "status": "LABEL_CALIBRATED_SOURCE_MK_CENSORING_NO_MODEL",
        "source_report": base,
        "current": base["current"],
        "coverage": {"selected_case_counts": FAMILY_COUNTS, "selected_case_count": len(cases), "selected_native_id_count": sum(x["native_count"] for x in cases), "structural_status_counts": status_counts, "family_structural_status": family_status},
        "cases": cases,
        "source_mk_summary": source_mk_summary,
        "floatinginfo_semantics": semantics,
        "controls": {
            "frozen_whole_initial_mass_gate_fraction": MASS_GATE,
            "gate_role": "screen only; no bounded velocity/force/coupling error and no QN/QE credit",
            "repeated_crossing": "UNKNOWN without a frame-resolved identity path beyond the completed scan fields",
            "signed_net_flux": "UNKNOWN",
            "destination_material_region": "UNKNOWN even with exact source MK",
            "manufactured_controls_are_tests_only": True,
        },
        "claim_boundary": {"physical_fate": "UNKNOWN", "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "raw_partout_opened": False, "decoder_started": False, "solver_started": False, "cfd_or_model_run": False},
    }


def runtime_source_paths() -> dict[str, Path]:
    """Return the exact shared runtime/dispatch files used by the request.

    These files live in the primary stage2 worktree because the shared runner
    owns the v8 entry point.  They are source inputs to the guard contract and
    therefore must be present in ``input_files`` as well as in the descriptive
    runtime bindings.  The evaluator itself never imports or executes them.
    """
    scripts = PRIMARY_LAB_ROOT / "scripts"
    return {
        "runtime_v8": scripts / "ds_data02_runtime_v8.py",
        "runtime_v6": scripts / "ds_data02_runtime_v6.py",
        "dispatch_v8": scripts / "ds_data02_stage2_dispatch_v8.py",
        "strict_v8": scripts / "ds_data02_strict_dispatch_v8.py",
    }


def load_f2_s1_reconciliation(closure: dict[str, Any]) -> dict[str, Any]:
    """Load the immutable, receipt-bound F2-S1 three-ID reconciliation."""
    item = closure.get("source_bindings", {}).get("old_native_reconciliation")
    path, reconciliation = get_path_binding(item, "F2-S1 old native reconciliation")
    reconciliation = read_json(path, "F2-S1 old native reconciliation")[1]
    if reconciliation.get("schema") != "ds02.stage2.native-exclusion-reconciliation.v1":
        raise LabelCalibrationError("F2-S1 old native reconciliation schema differs")
    if reconciliation.get("status") != "CAUSES_RECONCILED" or reconciliation.get("joined_count") != 3:
        raise LabelCalibrationError("F2-S1 old native reconciliation is not the exact three-ID closure")
    rows = reconciliation.get("missing_fluid_ids")
    if not isinstance(rows, list) or {row.get("idp") for row in rows if isinstance(row, dict)} != {397194, 403829, 404024}:
        raise LabelCalibrationError("F2-S1 old native reconciliation ID set differs")
    return reconciliation


def collect_inputs(report: dict[str, Any], closure: dict[str, Any], closure_path: Path,
                   official_paths: list[Path], base: dict[str, Any], f6_output_path: Path,
                   f6_receipt_path: Path, f6_bundle_path: Path,
                   f6_request_path: Path | None = None) -> dict[str, dict[str, Any]]:
    inputs: dict[str, dict[str, Any]] = {}
    for label, item in base.items():
        if isinstance(item, dict) and item.get("path"):
            path = require_file(item["path"], label)
            inputs[str(path)] = {**item, "digest_source": "completed_source_binding"}
    def add(path: Path | str, label: str, expected: str | None = None) -> None:
        item = binding(path, label, expected)
        previous = inputs.get(item["path"])
        if previous is not None and previous["sha256"] != item["sha256"]:
            raise LabelCalibrationError(f"conflicting source binding: {item['path']}")
        inputs[item["path"]] = {**item, "digest_source": "label_calibration_v1"}
    add(SCRIPT, "label calibration worker")
    add(closure_path, "F2-S1 exact source closure")
    for case in report["cases"]:
        source_files = case.get("source_files", {})
        for name in ("scan", "conversion_report"):
            item = source_files.get(name)
            if isinstance(item, dict) and item.get("path"):
                add(item["path"], f"{case.get('case_key')} {name}", item.get("sha256"))
    closure_bindings = closure.get("source_bindings", {})
    for name in ("current_conversion_report", "old_native_reconciliation", "old_native_reconciliation_receipt", "old_partvtkout_csv", "old_partvtkout_receipt", "runout", "runparts", "solver_receipt"):
        item = closure_bindings.get(name)
        if isinstance(item, dict):
            add(item["path"], f"F2-S1 closure {name}", item.get("sha256"))
    add(f6_output_path, "F6 Kabsch output")
    add(f6_receipt_path, "F6 Kabsch receipt")
    add(f6_bundle_path, "F6 Kabsch source bundle")
    if f6_request_path is not None:
        add(f6_request_path, "F6 Kabsch source request")
    # The bundle is only inspected for its already-registered small XML
    # bindings.  Its H5/BI4 paths are deliberately not added or opened.
    _, f6_bundle = read_json(f6_bundle_path, "F6 Kabsch source bundle")
    for row in f6_bundle.get("source_cases", []):
        if not isinstance(row, dict):
            continue
        case_id = row.get("physical_case_id", "unknown-case")
        xml_item = row.get("small_sources", {}).get("generated_xml_path")
        if isinstance(xml_item, dict):
            add(xml_item["path"], f"{case_id} generated XML", xml_item.get("sha256"))
    for path in official_paths:
        add(path, f"official source {path.name}")
    for name, path in runtime_source_paths().items():
        add(path, f"shared {name} source")
    return inputs


def prepare(output_dir: Path, v2_report_path: Path = V2_REPORT_DEFAULT, v2_receipt_path: Path = V2_RECEIPT_DEFAULT,
            v2_manifest_path: Path = V2_MANIFEST_DEFAULT, v2_request_path: Path = V2_REQUEST_DEFAULT,
            closure_path: Path = CLOSURE_DEFAULT, current_path: Path = CURRENT_DEFAULT,
            f6_output_path: Path = F6_OUTPUT_DEFAULT, f6_receipt_path: Path = F6_RECEIPT_DEFAULT,
            f6_bundle_path: Path = F6_BUNDLE_DEFAULT, official_paths: list[Path] | None = None,
            f6_request_path: Path | None = None, variant: str = "v1") -> dict[str, Any]:
    official_paths = official_paths or list(OFFICIAL_FILES_DEFAULT)
    report, receipt, base = validate_v2(v2_report_path, v2_receipt_path, v2_manifest_path, v2_request_path, current_path)
    closure = read_json(closure_path, "F2-S1 exact source closure")[1]
    load_f2_s1_reconciliation(closure)
    # Validate the already-completed F6 semantic source before creating a
    # launchable request.  This remains a JSON/XML/source-text audit only.
    semantics = floating_semantics(f6_output_path, f6_receipt_path, f6_bundle_path, official_paths)
    if len(semantics.get("cases", [])) != 2:
        raise LabelCalibrationError("F6 Kabsch semantic source does not contain the two frozen sentinels")
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"stage2-label-calibration-{variant}"
    manifest_path = output_dir / f"{name}-manifest.json"
    request_path = output_dir / f"{name}-request.json"
    if manifest_path.exists() or request_path.exists():
        raise LabelCalibrationError("refusing to overwrite prepared label request")
    inputs = collect_inputs(report, closure, closure_path, official_paths, base, f6_output_path, f6_receipt_path, f6_bundle_path, f6_request_path)
    input_files = sorted(inputs)
    input_bytes = sum(item["bytes"] for item in inputs.values())
    selected = sorted(str(case["case_key"]) for case in report["cases"])
    launch_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORKTREE_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    manifest = {
        "schema": "ds02.stage2.label-calibration-manifest.v1",
        "status": "PREPARED_ALL118_SOURCE_MK_CENSORING_NO_MODEL",
        "selected_case_counts": FAMILY_COUNTS,
        "selected_case_keys": selected,
        "selected_native_id_count": 1328,
        "input_files": input_files,
        "input_sha256": {path: inputs[path]["sha256"] for path in input_files},
        "input_bytes": {path: inputs[path]["bytes"] for path in input_files},
        "source_scope": {"h5_bytes_read": 0, "trajectory_bytes_read": 0, "raw_partout_bytes_read": 0, "decoder_started": False, "solver_started": False, "model_run": False, "source_mk_from_typed_blocks": True, "legacy_zone_not_used_as_mk": True},
        "claim_boundary": {"physical_fate": "UNKNOWN", "destination_material_region": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }
    atomic_json(manifest_path, manifest)
    inputs2 = dict(inputs)
    m = binding(manifest_path, "label calibration manifest")
    inputs2[str(manifest_path)] = m
    request_inputs = sorted(inputs2)
    request = {
        "schema": REQUEST_SCHEMA,
        "family_id": "infra",
        "case_id": "STAGE2_LABEL_CALIBRATION_ALL118_V1",
        "physical_case_id": "F2_F4_F6_ALL118_SOURCE_MK_CENSORING_LABELS",
        "attempt_id": f"{name}-primary-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "cwd": str(SCRIPT.parent),
        "worktree_root": str(WORKTREE_ROOT),
        "command": [str(VENV), str(SCRIPT), "audit", "--v2-report", str(v2_report_path), "--v2-receipt", str(v2_receipt_path), "--v2-manifest", str(v2_manifest_path), "--v2-request", str(v2_request_path), "--closure", str(closure_path), "--current", str(current_path), "--f6-output", str(f6_output_path), "--f6-receipt", str(f6_receipt_path), "--f6-bundle", str(f6_bundle_path), *sum((["--official-source", str(path)] for path in official_paths), []), "--output", f"{{attempt_root}}/{name}.json"],
        "input_files": request_inputs,
        "input_sha256": {path: inputs2[path]["sha256"] for path in request_inputs},
        "shared_runtime_version": "v8",
        "runtime_binding": {
            "runtime_v8": {"path": str(PRIMARY_LAB_ROOT / "scripts/ds_data02_runtime_v8.py"), "sha256": sha256(PRIMARY_LAB_ROOT / "scripts/ds_data02_runtime_v8.py")},
            "runtime_v6": {"path": str(PRIMARY_LAB_ROOT / "scripts/ds_data02_runtime_v6.py"), "sha256": sha256(PRIMARY_LAB_ROOT / "scripts/ds_data02_runtime_v6.py")},
        },
        "dispatch_binding": {"dispatch_v8": {"path": str(PRIMARY_LAB_ROOT / "scripts/ds_data02_stage2_dispatch_v8.py"), "sha256": sha256(PRIMARY_LAB_ROOT / "scripts/ds_data02_stage2_dispatch_v8.py")}},
        "strict_dispatch_binding": {"strict_v8": {"path": str(PRIMARY_LAB_ROOT / "scripts/ds_data02_strict_dispatch_v8.py"), "sha256": sha256(PRIMARY_LAB_ROOT / "scripts/ds_data02_strict_dispatch_v8.py")}},
        "source_read_cost": {"h5_bytes_read": 0, "trajectory_bytes_read": 0, "raw_partout_bytes_read": 0, "small_source_bytes_read": sum(item["bytes"] for item in inputs2.values()), "runtime_pre_post_hash_bytes": 2 * sum(item["bytes"] for item in inputs2.values()), "estimated_output_bytes": 64 * 1024 * 1024},
        "source_scope": {"selected_cases": FAMILY_COUNTS, "native_ids": 1328, "source_mk_from_typed_block_ranges": True, "legacy_zone_only_audit_context": True, "h5_content_read": False, "trajectory_content_read": False, "raw_partout_content_read": False, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
        "canonical_ready": True,
        "launch": True,
        "launch_allowed": True,
        "execution_allowed": True,
        "launch_owner": "root",
        "primary_launch_owner": "root",
        "shared_lease_required": True,
        "foreign_process_protection_required": True,
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "launch_commit": launch_commit,
        "request_note": "No-model source-MK/censoring label audit over completed all-118 small evidence. Exact source MK comes from typed conversion block ID ranges; scan Zone is never interpreted as MK/material/region. F6 FloatingInfo center/omega and frozen XML semantics are source-bound with physical COM/frame/Euler meaning kept UNKNOWN. No H5/BI4/OBI4, decoder, solver, CFD or model.",
    }
    atomic_json(request_path, request)
    return {"status": "prepared", "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "request": str(request_path), "request_sha256": sha256(request_path), "input_count": len(request_inputs), "input_bytes": request["source_read_cost"]["small_source_bytes_read"], "h5_opened": False, "launch_allowed": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--v2-report", type=Path, default=V2_REPORT_DEFAULT)
    common.add_argument("--v2-receipt", type=Path, default=V2_RECEIPT_DEFAULT)
    common.add_argument("--v2-manifest", type=Path, default=V2_MANIFEST_DEFAULT)
    common.add_argument("--v2-request", type=Path, default=V2_REQUEST_DEFAULT)
    common.add_argument("--closure", type=Path, default=CLOSURE_DEFAULT)
    common.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    common.add_argument("--f6-output", type=Path, default=F6_OUTPUT_DEFAULT)
    common.add_argument("--f6-receipt", type=Path, default=F6_RECEIPT_DEFAULT)
    common.add_argument("--f6-bundle", type=Path, default=F6_BUNDLE_DEFAULT)
    common.add_argument("--official-source", type=Path, action="append", dest="official_paths")
    aud = sub.add_parser("audit", parents=[common])
    aud.add_argument("--output", type=Path, required=True)
    prep = sub.add_parser("prepare", parents=[common])
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--variant", default="v1")
    args = parser.parse_args()
    official = args.official_paths or list(OFFICIAL_FILES_DEFAULT)
    try:
        if args.action == "audit":
            result = audit(args.v2_report, args.v2_receipt, args.v2_manifest, args.v2_request, args.closure, args.current, args.f6_output, args.f6_receipt, args.f6_bundle, official, args.output)
            atomic_json(args.output, result)
            print(json.dumps({"status": result["status"], "output": str(args.output.resolve()), "case_count": len(result["cases"]), "h5_opened": False, "structural_status_counts": result["coverage"]["structural_status_counts"]}, sort_keys=True))
        else:
            result = prepare(args.output_dir, args.v2_report, args.v2_receipt, args.v2_manifest, args.v2_request, args.closure, args.current, args.f6_output, args.f6_receipt, args.f6_bundle, official, variant=args.variant)
            print(json.dumps(result, sort_keys=True))
    except (LabelCalibrationError, ET.ParseError) as exc:
        raise SystemExit(f"LabelCalibrationError: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
