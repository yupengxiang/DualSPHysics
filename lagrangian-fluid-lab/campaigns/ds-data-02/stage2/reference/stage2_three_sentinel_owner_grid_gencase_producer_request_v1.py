#!/usr/bin/env python3
"""Prepare nine guarded, GenCase-only producer requests for the owner grid.

The frozen owner-grid V3 report contains three candidate definitions for each
of F2-S2, F3-S1, and F5-S1.  This builder turns each candidate into one
independent ``ds02.request.v1`` CPU request for the official GenCase binary.
It never runs GenCase, creates a candidate product, or reads native/VTK/BI4
payloads.  Generated XML/VTK/BI4 and the GenCase receipt are product-map
records that the parent reservation must establish after the guarded run.

The candidate ``*_Def.xml`` is itself the complete GenCase input case.  The
command therefore passes its stem (without ``.xml``), matching the successful
GenCase CLI convention already used by the campaign.  The only executable
operation in a future parent task is GenCase; solver launch remains false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

SCHEMA = "ds02.stage2.three-sentinel.owner-grid-gencase-producer-manifest.v1"
REQUEST_SCHEMA = "ds02.request.v1"
PRODUCT_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-gencase-product-map.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
SMALL_CAP = 10 * 1024 * 1024
PAYLOAD_SUFFIXES = {".bi4", ".vtk", ".vtu", ".h5", ".hdf5", ".part", ".hdf"}
OFFICIAL_GENCASE_SHA256 = "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
OWNER_REPORT_DEFAULT = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/three-sentinel-owner-grid-v3-primary-source-prepared-001/owner-grid-source-audit-v3.json"
RUNTIME_FILES = (
    PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
    PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
    PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
    PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_batch_runner.py",
    PRIMARY_REPO / "bin/linux/DsphConfig.xml",
    PRIMARY_REPO / "doc/xml_format/GenCase_CaseTemplate.xml",
)

QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class BuildFailure(RuntimeError):
    pass


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


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _record(
    path: Path,
    label: str,
    *,
    declared_sha: str | None = None,
    allow_deferred_large: bool = True,
    allow_payload_suffix: bool = False,
) -> dict[str, Any]:
    """Record a source without opening large/deferred files.

    Small source XML/JSON/Def/motion files are read and rehashed.  A file over
    the 10 MiB builder cap is stat-only, but its owner-declared SHA must be
    carried into the parent request; missing SHA is a hard preparation error.
    """
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    suffix = path.suffix.lower()
    if suffix in PAYLOAD_SUFFIXES and not allow_payload_suffix:
        raise BuildFailure(f"{label} is a forbidden native/payload input: {path}")
    before = _stat(path)
    if before["bytes"] > SMALL_CAP:
        if not allow_deferred_large:
            raise BuildFailure(f"{label} exceeds the bounded source cap: {path}")
        if not _valid_sha(declared_sha):
            raise BuildFailure(f"{label} is large and has no concrete owner SHA: {path}")
        return {
            "path": str(path),
            "sha256": str(declared_sha).lower(),
            "stat_before": before,
            "stat_after": before,
            "bytes": before["bytes"],
            "read_mode": "deferred_parent_after_reservation",
            "hash_status": "DECLARED_OWNER_V3_SHA_PARENT_REVERIFY_REQUIRED",
            "payload_read_by_builder": False,
            "scope": "deferred_control_source",
        }
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    digest = _sha(raw)
    if _valid_sha(declared_sha) and digest != str(declared_sha).lower():
        raise BuildFailure(f"{label} SHA differs from owner V3: {path}")
    return {
        "path": str(path),
        "sha256": digest,
        "stat_before": before,
        "stat_after": after,
        "bytes": before["bytes"],
        "read_mode": "small_read",
        "hash_status": "BOUND_SMALL_SOURCE",
        "payload_read_by_builder": True,
        "scope": "bounded_small_source",
    }


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > SMALL_CAP:
        raise BuildFailure(f"{label} exceeds the bounded JSON cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise BuildFailure(f"{label} changed during JSON read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be an object")
    return value, {
        "path": str(path),
        "sha256": _sha(raw),
        "stat_before": after,
        "stat_after": after,
        "bytes": after["bytes"],
        "read_mode": "small_read",
        "hash_status": "BOUND_SMALL_SOURCE",
        "payload_read_by_builder": True,
        "scope": "bounded_small_source",
    }


def _owner_rows(owner: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if owner.get("schema") != "ds02.stage2.three-sentinel.owner-grid-source-audit.v3":
        raise BuildFailure("owner report is not the frozen V3 source audit")
    cases = owner.get("cases")
    if not isinstance(cases, list):
        raise BuildFailure("owner report has no cases list")
    rows = {row.get("sentinel_id"): row for row in cases if isinstance(row, dict)}
    if set(rows) != set(TARGETS):
        raise BuildFailure("owner report must contain exactly F2-S2/F3-S1/F5-S1")
    return rows


def _grid_rows(case: dict[str, Any], sid: str) -> dict[str, dict[str, Any]]:
    values = case.get("source_requests")
    if not isinstance(values, list):
        raise BuildFailure(f"{sid} has no V3 source_requests")
    rows: dict[str, dict[str, Any]] = {}
    for row in values:
        if isinstance(row, dict) and row.get("grid_label") in GRIDS:
            label = str(row["grid_label"])
            if label in rows:
                raise BuildFailure(f"{sid} has duplicate {label} source request")
            rows[label] = row
    if set(rows) != set(GRIDS):
        raise BuildFailure(f"{sid} must contain original/coarse/fine source requests")
    return rows


def _owner_record(value: Any, label: str, *, allow_large: bool = True) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise BuildFailure(f"{label} lacks a path")
    return _record(Path(value["path"]), label, declared_sha=value.get("sha256"), allow_deferred_large=allow_large)


def _literal_python() -> dict[str, Any]:
    if not PYTHON.is_symlink() or not PYTHON.exists():
        raise BuildFailure(f"literal venv interpreter is unavailable: {PYTHON}")
    target = PYTHON.resolve()
    if not target.is_file() or not PYVENV.is_file():
        raise BuildFailure("literal venv target or pyvenv.cfg is unavailable")
    target_record = _record(target, "resolved venv interpreter", allow_deferred_large=False)
    cfg_record = _record(PYVENV, "pyvenv.cfg", allow_deferred_large=False)
    return {
        "literal_argv0": str(PYTHON),
        "resolved_target": str(target),
        "target_record": target_record,
        "pyvenv_record": cfg_record,
        "scope": "literal_venv_invocation_provenance",
    }


def _planned_root(sid: str, grid: str, attempt_id: str) -> Path:
    family = sid.split("-", 1)[0]
    return DATA_ROOT / "families" / family / f"{sid}_OWNER_GRID_GENCASE_{grid.upper()}_V1_ROOT_PENDING" / attempt_id


def _product_path(root: Path, name: str) -> dict[str, Any]:
    return {
        "path": str(root / name),
        "sha256": None,
        "stat": None,
        "hash_status": "PARENT_AFTER_GENCASE_REQUIRED",
        "payload_read_by_builder": False,
        "scope": "deferred_generated_product",
    }


def _append_unique(records: dict[str, dict[str, Any]], record: dict[str, Any], label: str | None = None) -> None:
    item = dict(record)
    if label:
        item["label"] = label
    path = str(item["path"])
    previous = records.get(path)
    if previous is None:
        records[path] = item
        return
    # A small re-read record is stronger than a stat-only/deferred occurrence.
    if previous.get("read_mode") != "small_read" and item.get("read_mode") == "small_read":
        records[path] = item


def _runtime_records() -> tuple[dict[str, Any], dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in RUNTIME_FILES:
        _append_unique(records, _record(path, f"runtime closure {path.name}", allow_deferred_large=False), path.name)
    python = _literal_python()
    _append_unique(records, python["target_record"], "resolved venv interpreter")
    _append_unique(records, python["pyvenv_record"], "pyvenv.cfg")
    return records, python


def _build_request(
    *,
    sid: str,
    grid: str,
    source: dict[str, Any],
    owner_case: dict[str, Any],
    owner_record: dict[str, Any],
    static: dict[str, dict[str, Any]],
    runtime: dict[str, Any],
    generator_record: dict[str, Any],
    output_root: Path,
    attempt_id: str,
    request_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    inputs = source.get("source_inputs")
    if not isinstance(inputs, dict):
        raise BuildFailure(f"{sid}:{grid} has no source_inputs")
    candidate_value = inputs.get("candidate_def")
    candidate = _owner_record(candidate_value, f"{sid}:{grid} candidate Def", allow_large=False)
    source_xml = _owner_record(inputs.get("source_xml"), f"{sid}:{grid} source XML", allow_large=False)
    source_def = _owner_record(inputs.get("source_def"), f"{sid}:{grid} source Def", allow_large=False)
    owner_source = owner_case.get("source_bindings") or {}
    source_receipt = _owner_record(owner_source.get("source_receipt"), f"{sid} source producer receipt", allow_large=False)
    for rec, label in ((candidate, "candidate Def"), (source_xml, "source XML"), (source_def, "source Def"), (source_receipt, "source receipt")):
        _append_unique(static, rec, f"{sid}:{grid} {label}")
    aux = inputs.get("motion_or_forcing")
    aux_record = None
    if isinstance(aux, dict) and isinstance(aux.get("path"), str):
        aux_record = _owner_record(aux, f"{sid}:{grid} motion/forcing", allow_large=True)
        _append_unique(static, aux_record, f"{sid}:{grid} motion/forcing")
    candidate_path = Path(candidate["path"])
    stem = str(candidate_path.with_suffix(""))
    if candidate_path.name.endswith("_Def.xml") is False:
        raise BuildFailure(f"{sid}:{grid} candidate must be a *_Def.xml GenCase case: {candidate_path}")
    output_products = {
        "generated_xml": _product_path(output_root, "generated.xml"),
        "fluid_vtk": _product_path(output_root, "generated_Fluid.vtk"),
        "bound_vtk": _product_path(output_root, "generated_Bound.vtk"),
        "native_bi4": _product_path(output_root, "generated.bi4"),
        "gencase_receipt": _product_path(output_root, "execution-receipt.json"),
    }
    row_key = f"{sid}:{grid}"
    request = {
        "schema": REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_CPU_GUARD_REVIEW_GENCASERUN_SOURCE_PREPARED",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "request_variant": "three-sentinel-owner-grid-gencase-producer-v1",
        "family_id": owner_case.get("family_id", sid.split("-", 1)[0]),
        "sentinel_id": sid,
        "physical_case_id": owner_case.get("physical_case_id"),
        "grid_label": grid,
        "row_key": row_key,
        "case_id": f"{sid.replace('-', '_')}_{grid.upper()}_OWNER_GRID_GENCASE_V1",
        "attempt_id": attempt_id,
        "command": [str(GENCASE), stem, "{attempt_root}/generated", "-save:all", "-threads:1"],
        "cwd": str(candidate_path.parent),
        "worktree_root": str(PRIMARY_REPO),
        "input_files": sorted(static),
        "input_records": static,
        "input_sha256": {path: rec["sha256"] for path, rec in static.items() if _valid_sha(rec.get("sha256"))},
        "input_hashes": {path: rec["sha256"] for path, rec in static.items() if _valid_sha(rec.get("sha256"))},
        "deferred_input_files": [aux_record["path"]] if aux_record and aux_record.get("read_mode") != "small_read" else [],
        "deferred_input_records": ([aux_record] if aux_record and aux_record.get("read_mode") != "small_read" else []),
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "max_memory_bytes": 4 * 1024**3,
        "max_storage_bytes": 64 * 1024**3,
        "estimated_input_read_bytes": sum(int(rec.get("bytes", 0)) for rec in static.values()),
        "estimated_storage_bytes": 0,
        "estimated_storage_status": "UNKNOWN_UNTIL_PARENT_GENCASE",
        "estimated_peak_memory_bytes": 4 * 1024**3,
        "execution_allowed": False,
        "launch_disabled": True,
        "solver_started": False,
        "solver_launch": False,
        "gencase_launch": True,
        "hdf5_read": False,
        "bi4_read": False,
        "output_root": "{attempt_root}",
        "planned_output_root": str(output_root),
        "output": {
            "atomic": True,
            "refuse_overwrite": True,
            "root": "{attempt_root}",
            "products": output_products,
        },
        "source_binding": {
            "owner_report": owner_record,
            "source_xml": source_xml,
            "source_def": source_def,
            "source_receipt": source_receipt,
            "candidate_def": candidate,
            "candidate_stem": stem,
            "candidate_definition_only_change": source.get("source_edit_contract"),
            "candidate_dp_m": source.get("candidate_dp_m"),
            "owner_region_predicate": inputs.get("owner_region_predicate"),
            "motion_or_forcing": aux_record,
            "official_gencase": generator_record,
            "parent_output_contract": "generated.xml, generated_Fluid.vtk, generated_Bound.vtk, generated.bi4, execution-receipt.json",
        },
        "runtime_provenance": runtime,
        "root_actual_launch_authority": "parent_shared_runtime_v8_only",
        "root_rebind_required": True,
        "source_only": True,
        "gencase_only": True,
        "read_scope": {
            "builder_reads_small_def_xml_and_owner_metadata": True,
            "builder_reads_large_forcing": False,
            "parent_hashes_deferred_control_after_reservation": True,
            "official_gencase_only": True,
            "solver_launch": False,
            "native_vtk_bi4_products_are_deferred": True,
        },
        "scientific_qualification": QUALIFICATION,
    }
    return request, output_products


def build(owner_report_path: Path, output_dir: Path) -> dict[str, Any]:
    owner, owner_record = _read_json(owner_report_path, "owner V3 source audit")
    owners = _owner_rows(owner)
    output_dir = _absolute(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BuildFailure(f"refusing overwrite of non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    request_dir = output_dir / "requests"
    request_dir.mkdir()
    static: dict[str, dict[str, Any]] = {owner_record["path"]: owner_record}
    # This module is itself a source input when the parent executes the
    # prepared requests.  It is source metadata only; no request invokes it.
    builder_path = _absolute(Path(__file__))
    builder_record = _record(builder_path, "GenCase producer request builder", allow_deferred_large=False)
    _append_unique(static, builder_record, "producer request builder")
    runtime_records, runtime = _runtime_records()
    for path, record in runtime_records.items():
        _append_unique(static, record, str(path))
    generator_record = _record(GENCASE, "official GenCase_linux64", declared_sha=OFFICIAL_GENCASE_SHA256, allow_deferred_large=False, allow_payload_suffix=True)
    if generator_record["sha256"] != OFFICIAL_GENCASE_SHA256:
        raise BuildFailure("official GenCase binary SHA differs from the declared campaign binary")
    _append_unique(static, generator_record, "official GenCase_linux64")
    request_values: list[dict[str, Any]] = []
    product_rows: list[dict[str, Any]] = []
    all_static_paths: set[str] = set()
    for sid in TARGETS:
        case = owners[sid]
        rows = _grid_rows(case, sid)
        for grid in GRIDS:
            attempt = f"{sid.lower().replace('-', '-')}-{grid}-owner-grid-gencase-v1-parent-pending-001"
            root = _planned_root(sid, grid, attempt)
            # Each request receives a snapshot of the accumulated closure plus
            # its own candidate/control records.  Build with a local map first.
            local_static = dict(static)
            req_name = f"{sid.lower()}-{grid}-owner-grid-gencase-v1-request.json"
            req_path = request_dir / req_name
            request, products = _build_request(
                sid=sid,
                grid=grid,
                source=rows[grid],
                owner_case=case,
                owner_record=owner_record,
                static=local_static,
                runtime=runtime,
                generator_record=generator_record,
                output_root=root,
                attempt_id=attempt,
                request_path=req_path,
            )
            # The builder itself and owner report are the shared closure; the
            # per-row source files were added to local_static by _build_request.
            req_path.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
            request_record = _record(req_path, f"prepared GenCase request {sid}:{grid}", allow_deferred_large=False)
            request_values.append(request)
            product_rows.append({
                "sentinel_id": sid,
                "grid_label": grid,
                "row_key": f"{sid}:{grid}",
                "physical_case_id": case.get("physical_case_id"),
                "case_id": request["case_id"],
                "attempt_id": attempt,
                "producer_request": request_record,
                "planned_output_root": str(root),
                "generated_xml": products["generated_xml"],
                "fluid_vtk": products["fluid_vtk"],
                "bound_vtk": products["bound_vtk"],
                "native_bi4": products["native_bi4"],
                "gencase_receipt": products["gencase_receipt"],
                "native_header_probe": {"status": "PARENT_AFTER_GENCASE_REQUIRED", "path": str(root / "native-header.json")},
                "status": "PENDING_PARENT_GUARDED_GENCASE",
                "scientific_qualification": QUALIFICATION,
            })
            all_static_paths.update(local_static)
    # Product map is deliberately written only after the nine immutable
    # producer requests exist; it binds each row to its exact producer SHA.
    map_value = {
        "schema": PRODUCT_SCHEMA,
        "status": "PENDING_PARENT_GUARDED_GENCASE",
        "owner_report": owner_record,
        "official_gencase": generator_record,
        "producer_request_count": len(product_rows),
        "products": product_rows,
        "read_scope": {
            "request_builder_read_products": False,
            "generated_products_exist": False,
            "parent_after_reservation_product_sha_stat": True,
            "solver_launch": False,
            "scientific_credit": 0,
        },
        "scientific_qualification": QUALIFICATION,
    }
    map_path = output_dir / "owner-grid-gencase-product-map-v1.json"
    map_path.write_text(json.dumps(map_value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    map_record = _record(map_path, "nine-row GenCase product map", allow_deferred_large=False)
    manifest = {
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_SHARED_RUNTIME_V8_GENCASERUNS",
        "owner_report": owner_record,
        "official_gencase": generator_record,
        "producer_requests": [
            {"path": str(request_dir / f"{sid.lower()}-{grid}-owner-grid-gencase-v1-request.json"),
             "sha256": next(item["producer_request"]["sha256"] for item in product_rows if item["sentinel_id"] == sid and item["grid_label"] == grid),
             "row_key": f"{sid}:{grid}"}
            for sid in TARGETS for grid in GRIDS
        ],
        "product_map": map_record,
        "rows": product_rows,
        "static_source_count": len(all_static_paths),
        "read_scope": {
            "source_metadata_only": True,
            "large_control_files_deferred": True,
            "generated_products_deferred": True,
            "gencase_launch_by_builder": False,
            "solver_launch": False,
            "scientific_credit": 0,
        },
        "scientific_qualification": QUALIFICATION,
    }
    manifest_path = output_dir / "owner-grid-gencase-producer-manifest-v1.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    # Keep the final manifest outside its own JSON record.  A self-record would
    # necessarily become stale on rewrite; the parent hashes this final file
    # after reservation, while the product map and each producer request carry
    # their immutable records.
    manifest_record = _record(manifest_path, "nine-row GenCase producer manifest", allow_deferred_large=False)
    return {
        "manifest": manifest,
        "manifest_record": manifest_record,
        "manifest_path": str(manifest_path),
        "product_map": map_value,
        "product_map_path": str(map_path),
        "producer_requests": len(request_values),
        "producer_request_paths": [str(request_dir / f"{sid.lower()}-{grid}-owner-grid-gencase-v1-request.json") for sid in TARGETS for grid in GRIDS],
    }


def _self_test() -> None:
    # This deliberately tests only the non-payload path helpers.  A real
    # owner-report build is run separately against the frozen V3 metadata in
    # the source-preparation validation command.
    assert _planned_root("F2-S2", "coarse", "attempt").name == "attempt"
    assert str(Path("x_Def.xml").with_suffix("")) == "x_Def"
    try:
        _record(Path("/definitely/missing/fixture.bi4"), "negative payload")
    except (BuildFailure, OSError):
        pass
    else:
        raise AssertionError("missing payload was accepted")
    print("PASS_THREE_SENTINEL_GENCASE_PRODUCER_REQUEST_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--owner-report", type=Path, default=OWNER_REPORT_DEFAULT)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            _self_test()
        except Exception as exc:
            print(f"FAILED_THREE_SENTINEL_GENCASE_PRODUCER_REQUEST_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.output_dir is None:
        parser.error("--build requires --output-dir")
    try:
        result = build(args.owner_report, args.output_dir)
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_GENCASE_PRODUCER_REQUEST: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["manifest"]["status"], "manifest": result["manifest_path"],
                      "product_map": result["product_map_path"], "producer_requests": result["producer_requests"],
                      "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
