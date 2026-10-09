#!/usr/bin/env python3
"""Prepare a source-bound initial-geometry admission graph for four sentinels.

This is deliberately a metadata-only preparer.  It follows the terminal
GenCase receipt to the generated XML and records the generated Fluid/Bound
VTK and BI4 files by stat only.  The VTK and BI4 bytes are inputs for a later
parent-reserved worker; this program never opens or hashes them.  The output
therefore makes the next support/owner check concrete without granting
initial-state, continuous-owner, three-grid, or numerical credit.

The four rows are the existing F2-S2, F4-S2, F5-S2 and F7-S1 products.  No
new GenCase run is started.  A request emitted by this program is explicitly
source-prepared and launch-disabled until a parent binds an actual VTK
support worker and performs after-reservation pre/post hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
QUALITY_REL = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_reference_quality_cost_v2.json")
SOURCE_STATUS_REL = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_fourteen_source_status_v3.json")
READINESS_REL = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_fourteen_scientific_readiness_v5.json")
CASES = ("F2-S2", "F4-S2", "F5-S2", "F7-S1")
SCHEMA = "ds02.stage2.four-sentinel-gencase-geometry-admission.v1"
REQUEST_SCHEMA = "ds02.request.v1"
MAX_SMALL_BYTES = 16 * 1024 * 1024


class BuildFailure(RuntimeError):
    """Raised when a source binding is incomplete or changed during a read."""


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _regular(path: Path, label: str) -> Path:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _small_bytes(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    """Read and hash one bounded byte image, then parse only that image."""
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise BuildFailure(f"{label} exceeds bounded metadata input: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    return raw, {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "stat": after,
        "hash_status": "BOUND_SMALL_METADATA",
        "payload_read_by_builder": True,
    }


def _small_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, record = _small_bytes(path, label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be a JSON object: {path}")
    return value, record


def _stat_only(path: Path, label: str, *, required: bool = True) -> dict[str, Any]:
    """Record a deferred product without opening it or computing its SHA."""
    path = _absolute(path)
    if path.is_symlink():
        raise BuildFailure(f"{label} must not be a symlink: {path}")
    if not path.exists():
        if required:
            return {
                "path": str(path),
                "status": "MISSING_SOURCE_PRODUCT",
                "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
                "payload_read_by_builder": False,
            }
        return {
            "path": str(path),
            "status": "NOT_PRESENT_OPTIONAL",
            "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
            "payload_read_by_builder": False,
        }
    if not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    value = _stat(path)
    return {
        "path": str(path),
        "status": "PRESENT_STAT_ONLY",
        "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
        "stat": value,
        "payload_read_by_builder": False,
    }


def _write_once(path: Path, value: Any) -> None:
    path = _absolute(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _sha_from_map(value: Any, path: Path) -> str | None:
    if not isinstance(value, dict):
        return None
    item = value.get(str(_absolute(path)))
    return item if isinstance(item, str) and len(item) == 64 else None


def _find_gencase_receipt(row: dict[str, Any], source_xml: Path, source_xml_sha: str) -> tuple[Path, dict[str, Any], dict[str, Any], Path]:
    """Find the terminal GenCase receipt whose generated XML is this source."""
    controls = row.get("source_solver_controls") or {}
    launch_map = controls.get("input_hashes_at_launch")
    if not isinstance(launch_map, dict):
        raise BuildFailure(f"{row.get('sentinel_id')} has no source solver input map")
    candidates: list[tuple[Path, dict[str, Any], dict[str, Any], Path]] = []
    for value in launch_map:
        candidate = Path(str(value))
        if candidate.name != "execution-receipt.json" or "gencase" not in str(candidate).lower():
            continue
        try:
            receipt, receipt_record = _small_json(candidate, f"{row.get('sentinel_id')} GenCase receipt")
        except BuildFailure:
            continue
        if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
            continue
        output_root_value = receipt.get("output_root")
        if not isinstance(output_root_value, str):
            continue
        output_root = _absolute(Path(output_root_value))
        generated_xml = output_root / "prepared" / source_xml.name
        if not generated_xml.exists() or generated_xml.is_symlink() or not generated_xml.is_file():
            continue
        generated_raw, generated_record = _small_bytes(generated_xml, f"{row.get('sentinel_id')} generated XML")
        if generated_record["sha256"] != source_xml_sha:
            continue
        candidates.append((candidate, receipt, receipt_record, output_root))
    if len(candidates) != 1:
        raise BuildFailure(f"{row.get('sentinel_id')} expected one exact terminal GenCase product, found {len(candidates)}")
    return candidates[0]


def _identity(receipt: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    request = receipt.get("request")
    actual = request if isinstance(request, dict) else {}
    keys = ("family_id", "physical_case_id", "case_id", "attempt_id")
    status: dict[str, str] = {}
    for key in keys:
        expected = row.get(key if key != "case_id" else "runtime_case_alias")
        observed = actual.get(key)
        if expected is None:
            # The quality row does not declare an attempt for a historical
            # GenCase product.  That is a provenance gap, not an identity
            # mismatch; retain the producer value separately below.
            status[key] = "NOT_DECLARED_SOURCE_ROW"
        elif observed is None:
            status[key] = "MISSING_PRODUCER_FIELD"
        else:
            status[key] = "MATCH" if observed == expected else "DIFFERENT"
    # The source quality row's physical_case_id is the authoritative label for
    # the intended product, but a missing producer field stays missing; this
    # function never promotes the label to producer evidence.
    return {
        "producer_request": {key: actual.get(key) for key in keys},
        "source_row": {key: row.get(key if key != "case_id" else "runtime_case_alias") for key in keys},
        "field_status": status,
        "producer_physical_case_id_status": "PRESENT" if isinstance(actual.get("physical_case_id"), str) else "MISSING",
        "producer_identity_scope": "PARTIAL_WHERE_FIELDS_MISSING; no label fallback",
    }


def _source_xml_solver_join(receipt: dict[str, Any], source_xml: Path, source_xml_sha: str) -> dict[str, Any]:
    request = receipt.get("request")
    xml_path = str(_absolute(source_xml))
    checks: dict[str, Any] = {}
    if not isinstance(request, dict):
        return {"status": "UNKNOWN_NO_NESTED_SOLVER_REQUEST", "path": xml_path, "sha256": source_xml_sha}
    request_hashes = request.get("input_sha256")
    checks["request_input_sha256"] = isinstance(request_hashes, dict) and request_hashes.get(xml_path) == source_xml_sha
    for name in ("input_hashes_at_launch", "input_hashes_after_run"):
        hashes = receipt.get(name)
        checks[name] = isinstance(hashes, dict) and hashes.get(xml_path) == source_xml_sha
    return {
        "status": "PASS_SOURCE_XML_SOLVER_RECEIPT_HASH_JOIN" if all(checks.values()) else "PARTIAL_SOURCE_XML_SOLVER_RECEIPT_HASH_JOIN",
        "path": xml_path,
        "sha256": source_xml_sha,
        "checks": checks,
    }


def _motion_records(row: dict[str, Any], solver_receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose motion input paths from the receipt as stat-only metadata."""
    mapping = solver_receipt.get("input_hashes_at_launch")
    if not isinstance(mapping, dict):
        return []
    refs = set(str(value) for value in (row.get("source_xml") or {}).get("motion_refs", []) if isinstance(value, str))
    hits: list[dict[str, Any]] = []
    for raw_path, digest in mapping.items():
        path = Path(str(raw_path))
        if path.suffix.lower() not in (".dat", ".csv"):
            continue
        if refs and not any(path.name == Path(ref).name for ref in refs):
            continue
        record = _stat_only(path, f"{row.get('sentinel_id')} motion source", required=False)
        record["declared_sha256_from_solver_receipt"] = digest if isinstance(digest, str) and len(digest) == 64 else None
        hits.append(record)
    # Keep one record per path and deterministic order.  Duplicate XML motion
    # references do not imply two physical input files.
    unique: dict[str, dict[str, Any]] = {item["path"]: item for item in hits}
    return [unique[key] for key in sorted(unique)]


def _owner_contract(sentinel_id: str, row: dict[str, Any]) -> dict[str, Any]:
    native_mass = row.get("source_sample_mass_kg")
    if sentinel_id == "F2-S2":
        owner_mass = 18.876
        relative = (float(native_mass) - owner_mass) / owner_mass * 100.0 if native_mass is not None else None
        return {
            "status": "KNOWN_OWNER_TARGET_SUPPORT_UNVERIFIED",
            "continuous_owner_mass_kg": owner_mass,
            "native_xml_sample_mass_kg": native_mass,
            "native_sample_vs_owner_relative_pct": relative,
            "mass_rule": "native sample mass is diagnostic; no rescale and no continuum-owner credit",
            "missing_evidence": ["Fluid/Bound payload support and overlap", "owner geometry volume/support equivalence"],
        }
    return {
        "status": "UNKNOWN_CONTINUOUS_OWNER",
        "continuous_owner_mass_kg": None,
        "native_xml_sample_mass_kg": native_mass,
        "mass_rule": "native sample mass is diagnostic only; no mass-fit or rescale",
        "missing_evidence": ["source-bound continuous owner definition", "owner volume/support equivalence", "Fluid/Bound payload support and overlap"],
    }


def _source_case(row: dict[str, Any], source_status: dict[str, Any], readiness: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    sid = str(row.get("sentinel_id"))
    source_xml = _absolute(Path(str((row.get("source_xml") or {}).get("path", ""))))
    source_xml_raw, source_xml_record = _small_bytes(source_xml, f"{sid} source XML")
    declared = (row.get("source_xml") or {}).get("file") or {}
    if isinstance(declared.get("sha256"), str) and declared["sha256"] != source_xml_record["sha256"]:
        raise BuildFailure(f"{sid} source XML SHA differs from quality manifest")
    gencase_path, gencase, gencase_record, output_root = _find_gencase_receipt(row, source_xml, source_xml_record["sha256"])
    generated_xml = output_root / "prepared" / source_xml.name
    _, generated_xml_record = _small_bytes(generated_xml, f"{sid} generated XML")
    stem = source_xml.stem
    products = {
        "generated_xml": generated_xml_record,
        "generated_bi4": _stat_only(output_root / "prepared" / f"{stem}.bi4", f"{sid} generated BI4"),
        "fluid_vtk": _stat_only(output_root / "prepared" / f"{stem}_Fluid.vtk", f"{sid} generated Fluid VTK"),
        "bound_vtk": _stat_only(output_root / "prepared" / f"{stem}_Bound.vtk", f"{sid} generated Bound VTK"),
        "all_vtk": _stat_only(output_root / "prepared" / f"{stem}_All.vtk", f"{sid} generated All VTK", required=False),
        "mkcells_vtk": _stat_only(output_root / "prepared" / f"{stem}_MkCells.vtk", f"{sid} generated MkCells VTK", required=False),
        "generated_def_xml": _stat_only(output_root / "prepared" / f"{stem}_Def.xml", f"{sid} generated Def XML", required=False),
    }
    if products["fluid_vtk"]["status"] != "PRESENT_STAT_ONLY" or products["bound_vtk"]["status"] != "PRESENT_STAT_ONLY":
        vtk_status = "MISSING_REQUIRED_FLUID_OR_BOUND_VTK"
    else:
        vtk_status = "PRESENT_STAT_ONLY_PARENT_HASH_REQUIRED"
    binding = row.get("current_row_binding") or {}
    solver_info = binding.get("solver_receipt") or {}
    if not isinstance(solver_info.get("path"), str):
        raise BuildFailure(f"{sid} missing current solver receipt path")
    solver_path = _absolute(Path(solver_info["path"]))
    solver, solver_record = _small_json(solver_path, f"{sid} current solver receipt")
    if solver.get("status") != "completed" or int(solver.get("returncode", -1)) != 0:
        raise BuildFailure(f"{sid} current solver receipt is not completed rc=0")
    source_solver_join = _source_xml_solver_join(solver, source_xml, source_xml_record["sha256"])
    source_status_row = next((item for item in source_status.get("sentinels", []) if isinstance(item, dict) and item.get("sentinel_id") == sid), None)
    readiness_row = next((item for item in readiness.get("sentinels", []) if isinstance(item, dict) and item.get("sentinel_id") == sid), None)
    if not isinstance(source_status_row, dict) or not isinstance(readiness_row, dict):
        raise BuildFailure(f"{sid} missing status/readiness row")
    status_evidence = []
    for item in source_status_row.get("evidence", []):
        if not isinstance(item, dict):
            continue
        file_record = item.get("file") if isinstance(item.get("file"), dict) else {}
        status_evidence.append({
            "claim_scope": item.get("claim_scope"),
            "kind": item.get("kind"),
            "path": file_record.get("path") or item.get("path") or item.get("name"),
            "declared_sha256": file_record.get("sha256"),
            "declared_bytes": file_record.get("bytes"),
            "source_status_content_read_by_builder": False,
        })
    owner = _owner_contract(sid, row)
    motion = _motion_records(row, solver)
    generated_counts = {
        "total_particles": gencase.get("total_particles"),
        "fluid_particles": gencase.get("fluid_particles"),
        "source_xml_fluid_particle_count": (row.get("source_xml") or {}).get("fluid_particle_count"),
        "source_xml_sample_mass_kg": (row.get("source_xml") or {}).get("sample_mass_kg"),
    }
    case = {
        "sentinel_id": sid,
        "family_id": row.get("family_id"),
        "source_row_physical_case_id": row.get("physical_case_id"),
        "source_row_runtime_case_alias": row.get("runtime_case_alias"),
        "source_xml": source_xml_record,
        "source_geometry_metadata": {
            "dp_m": (row.get("source_xml") or {}).get("dp_m"),
            "h_m": (row.get("source_xml") or {}).get("h_m"),
            "fluid_blocks": (row.get("source_xml") or {}).get("fluid_blocks"),
            "fluid_particle_count": (row.get("source_xml") or {}).get("fluid_particle_count"),
            "massfluid_values_kg": (row.get("source_xml") or {}).get("massfluid_values_kg"),
            "xml_sample_mass_kg": (row.get("source_xml") or {}).get("sample_mass_kg"),
            "execution_parameters": (row.get("source_xml") or {}).get("parameters"),
            "motion_refs": (row.get("source_xml") or {}).get("motion_refs"),
            "effective_time_window_s": row.get("effective_time_window_s"),
            "window_end_s": row.get("window_end_s"),
            "source_cfl": row.get("source_cfl"),
            "half_cfl": row.get("half_cfl"),
            "effective_output_cadence_s": row.get("effective_output_cadence_s"),
            "owner_geometry_semantics": "NOT_ESTABLISHED_BY_XML_AND_METADATA_ONLY; requires guarded Fluid/Bound support and source owner contract",
        },
        "gencase": {
            "receipt": gencase_record,
            "receipt_path": str(gencase_path),
            "status": gencase.get("status"),
            "returncode": gencase.get("returncode"),
            "output_root": str(output_root),
            "identity": _identity(gencase, row),
            "generated_xml_exact_sha_match": generated_xml_record["sha256"] == source_xml_record["sha256"],
            "generated_products": products,
            "counts": generated_counts,
        },
        "current_solver": {
            "receipt": solver_record,
            "status": solver.get("status"),
            "returncode": solver.get("returncode"),
            "source_xml_join": source_solver_join,
            "command": (row.get("source_solver_controls") or {}).get("command"),
            "tmax_s": (row.get("source_solver_controls") or {}).get("tmax_s"),
            "tout_s": (row.get("source_solver_controls") or {}).get("tout_s"),
            "motion_inputs": motion,
        },
        "source_status": {
            "terminal_state": source_status_row.get("terminal_state"),
            "next_guarded_task": source_status_row.get("next_guarded_task"),
            "evidence_declarations": status_evidence,
        },
        "readiness_status": {
            "initial_support_status": readiness_row.get("initial_support_status"),
            "owner_status": readiness_row.get("owner_status"),
            "control_status": readiness_row.get("control_status"),
            "three_grid_status": readiness_row.get("three_grid_status"),
            "window_status": readiness_row.get("window_status"),
        },
        "continuous_owner": owner,
        "admission": {
            "source_xml_and_gencase_product": "PASS_EXACT_GENERATED_XML_AND_TERMINAL_GENCASE_RECEIPT",
            "fluid_bound_vtk_product": vtk_status,
            "payload_support_overlap": "UNKNOWN_PARENT_GUARDED_VTK_READ_REQUIRED",
            "source_control": source_solver_join["status"],
            "initial_support_gate": "PENDING_PARENT_GUARDED_FLUID_BOUND_VTK_AUDIT",
            "continuous_owner_gate": owner["status"],
            "three_grid_solver_admission": "BLOCKED_UNTIL_SUPPORT_OWNER_CONTROL_GATES_CLOSE",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "required_parent_worker_checks": {
            "deferred_payloads": [products["generated_bi4"], products["fluid_vtk"], products["bound_vtk"]],
            "after_reservation": "SHA/stat before, immediately after, and after decode for every deferred product; source replacement/touch fails",
            "fluid_vtk": ["points finite", "Idp/MK role mapping if present", "fluid count vs XML count", "inside continuous-owner support region", "native mass only when encoded and separate from XML sample mass"],
            "bound_vtk": ["points finite", "fixed/moving/floating role mapping", "fluid-bound overlap/contact/gap", "domain envelope", "no inferred no-penetration or flux from point counts"],
            "identity": "producer request/output root/generated XML and current solver source XML hash must join exactly; missing physical_case_id remains partial/UNKNOWN",
            "no_rescale": True,
            "neighbor_grid_truth": False,
        },
        "payload_read_by_builder": False,
        "builder_read_scope": {"small_xml_receipts_json": True, "vtk_payload": False, "bi4_payload": False, "hdf5": False, "solver_launch": False},
    }
    records: dict[str, dict[str, Any]] = {}
    for record in (source_xml_record, gencase_record, generated_xml_record, solver_record):
        records[record["path"]] = record
    for product in products.values():
        records[product["path"]] = product
    for motion_record in motion:
        records[motion_record["path"]] = motion_record
    return case, records


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    quality, quality_record = _small_json(args.quality, "quality manifest")
    source_status, source_status_record = _small_json(args.source_status, "fourteen source status")
    readiness, readiness_record = _small_json(args.readiness, "scientific readiness")
    rows = {str(row.get("sentinel_id")): row for row in quality.get("sources", []) if isinstance(row, dict)}
    if set(CASES) - set(rows):
        raise BuildFailure(f"quality manifest lacks cases: {sorted(set(CASES) - set(rows))}")
    cases: list[dict[str, Any]] = []
    records: dict[str, dict[str, Any]] = {
        quality_record["path"]: quality_record,
        source_status_record["path"]: source_status_record,
        readiness_record["path"]: readiness_record,
    }
    for sid in CASES:
        case, case_records = _source_case(rows[sid], source_status, readiness)
        cases.append(case)
        records.update(case_records)
    report = {
        "schema": SCHEMA,
        "status": "SOURCE_METADATA_READY_PARENT_VTK_SUPPORT_REQUIRED",
        "generated_by": {"path": str(_absolute(Path(__file__))), "payload_read": False, "solver_launch": False},
        "source_quality_manifest": quality_record,
        "source_status_manifest": source_status_record,
        "readiness_manifest": readiness_record,
        "cases": cases,
        "aggregate_admission": {
            "all_four_have_terminal_gencase_xml_exact_match": all(c["gencase"]["generated_xml_exact_sha_match"] for c in cases),
            "all_four_have_fluid_bound_vtk_stat_paths": all(c["admission"]["fluid_bound_vtk_product"] == "PRESENT_STAT_ONLY_PARENT_HASH_REQUIRED" for c in cases),
            "support_overlap_closed": False,
            "continuous_owner_closed": False,
            "eligible_for_three_grid_solver": False,
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
        "read_scope": {
            "small_metadata_bytes_read": True,
            "vtk_payload_read": False,
            "bi4_payload_read": False,
            "hdf5_read": False,
            "solver_started": False,
            "vtk_hashes": "NOT_COMPUTED_BY_BUILDER; parent after reservation required",
        },
        "next_parent_action": {
            "kind": "PARENT_GUARDED_FOUR_SENTINEL_INITIAL_SUPPORT_AUDIT",
            "action": "Bind one VTK/BI4-capable worker to the exact generated products below, reserve first, then audit Fluid/Bound support, role overlap, and owner/control joins before any three-grid solver request.",
            "reuse_existing_gencase": True,
            "new_gencase_required": False,
            "new_solver_required": False,
        },
    }
    report_path = _absolute(args.report_output)
    _write_once(report_path, report)
    report_record = _small_bytes(report_path, "admission report")[1]
    records[report_record["path"]] = report_record
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": SCHEMA,
        "status": "SOURCE_PREPARED_PARENT_VTK_SUPPORT_REQUIRED",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "request_id": "four-sentinel-gencase-geometry-admission-v1-source-prepared-001",
        "family_id": "DS02-MULTI",
        "sentinel_ids": list(CASES),
        "case_id": "FOUR_SENTINEL_GENCASE_GEOMETRY_ADMISSION_V1",
        "attempt_id": "PARENT_REBIND_REQUIRED_ROOT314",
        "worktree_root": str(PRIMARY),
        "cwd": str(PRIMARY),
        "command": [],
        "execution_allowed": False,
        "launch_disabled": True,
        "input_files": sorted(records),
        "input_sha256": {path: value["sha256"] for path, value in sorted(records.items()) if isinstance(value.get("sha256"), str)},
        "input_records": records,
        "report": report_record,
        "cases": [{
            "sentinel_id": case["sentinel_id"],
            "physical_case_id": case["source_row_physical_case_id"],
            "generated_xml": case["gencase"]["generated_products"]["generated_xml"],
            "generated_bi4": case["gencase"]["generated_products"]["generated_bi4"],
            "fluid_vtk": case["gencase"]["generated_products"]["fluid_vtk"],
            "bound_vtk": case["gencase"]["generated_products"]["bound_vtk"],
            "gencase_receipt": case["gencase"]["receipt"],
            "current_solver_receipt": case["current_solver"]["receipt"],
            "continuous_owner": case["continuous_owner"],
            "deferred_parent_hash_required": True,
        } for case in cases],
        "deferred_input_policy": {
            "parent_v8_deferred_fields_not_credit": True,
            "actual_parent_input_files_must_be_explicit": True,
            "worker_first_sha_stat": True,
            "worker_post_decode_sha_stat": True,
            "source_replace_or_touch": "FAIL",
            "native_and_vtk_payload_reads": "parent-reserved only",
        },
        "resources_planning_only": {
            "cpu_threads": 1,
            "max_wall_seconds": 1800,
            "memory_max_bytes": 2 * 1024**3,
            "scratch_max_bytes": 512 * 1024**2,
            "gpu": "none",
            "solver_launch": False,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "source_binding": {
            "exact_terminal_gencase_xml": True,
            "fluid_bound_vtk_payload": "DEFERRED",
            "continuous_owner": "EXPLICIT_PER_CASE_STATUS",
            "mass_rescale": False,
            "neighbor_grid_truth": False,
        },
    }
    _write_once(_absolute(args.request_output), request)
    return report, request


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="four-sentinel-admission-") as td:
        root = Path(td)
        small = root / "small.json"
        small.write_text('{"ok": true}\n', encoding="utf-8")
        value, rec = _small_json(small, "fixture")
        assert value["ok"] is True and rec["sha256"]
        payload = root / "deferred.vtk"
        payload.write_bytes(b"vtk payload that must not be opened")
        stat = _stat_only(payload, "deferred fixture")
        assert stat["status"] == "PRESENT_STAT_ONLY" and stat["sha256"] if "sha256" in stat else True
        assert stat["payload_read_by_builder"] is False
        missing = _stat_only(root / "missing.bi4", "missing fixture")
        assert missing["status"] == "MISSING_SOURCE_PRODUCT"
    print("PASS_FOUR_SENTINEL_GENCASE_GEOMETRY_ADMISSION_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--quality", type=Path, default=PRIMARY / QUALITY_REL)
    parser.add_argument("--source-status", type=Path, default=PRIMARY / SOURCE_STATUS_REL)
    parser.add_argument("--readiness", type=Path, default=PRIMARY / READINESS_REL)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--request-output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.report_output is None or args.request_output is None:
        parser.error("--build requires --report-output and --request-output")
    try:
        report, request = build(args)
    except (BuildFailure, OSError, ValueError) as exc:
        print(f"FAILED_FOUR_SENTINEL_GENCASE_GEOMETRY_ADMISSION: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "cases": [c["sentinel_id"] for c in report["cases"]], "report": str(_absolute(args.report_output)), "request": str(_absolute(args.request_output)), "support_overlap_closed": report["aggregate_admission"]["support_overlap_closed"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
