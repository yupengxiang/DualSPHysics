#!/usr/bin/env python3
"""Prepare runtime-v8-compatible owner-grid GenCase requests.

This is an additive repair for the frozen V1 source package.  V1 remains
unchanged and is used only as the reviewed source-audit reader.  V2 fixes the
runtime identity contract: the attempt directory is exactly
``families/<family>/<case_id>/<attempt_id>``, all nine product-map rows use the
same identity, and deferred controls are kept in ``deferred_input_records``
but removed from runtime-v8 ``input_files`` and digest maps.

The official command receives the candidate XML stem including ``_Def`` and
without the final ``.xml``.  Its output prefix is ``{attempt_root}/generated``;
the expected product names are the normal generated XML, Fluid/Bound VTK,
BI4, and runtime-v8 ``execution-receipt.json``.  This module only prepares
requests and a product map.  It never runs GenCase or reads native products.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_three_sentinel_owner_grid_gencase_producer_request_v1.py"
SPEC = importlib.util.spec_from_file_location("stage2_owner_grid_gencase_v1_frozen", V1_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load frozen V1 producer builder: {V1_PATH}")
V1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V1)

SCHEMA = "ds02.stage2.three-sentinel.owner-grid-gencase-producer-manifest.v2"
PRODUCT_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-gencase-product-map.v2"
REQUEST_VARIANT = "three-sentinel-owner-grid-gencase-producer-v2"
REQUEST_SCHEMA = "ds02.request.v1"
TARGETS = tuple(V1.TARGETS)
GRIDS = tuple(V1.GRIDS)
SMALL_CAP = int(V1.SMALL_CAP)
STORAGE_FLOOR = 512 * 1024**2
STORAGE_CAP = 8 * 1024**3
PER_PARTICLE_STORAGE_BYTES = 4096
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CLI_EVIDENCE = PRIMARY_REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_f3_s2_owner_centered_gencase_prefix_forward_v1.py"
)
SOURCE_AUDIT = PRIMARY_REPO / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_three_sentinel_owner_grid_source_audit_v3.py"
)
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class BuildFailure(RuntimeError):
    pass


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _read_json(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    stat = path.stat()
    if stat.st_size > SMALL_CAP:
        raise BuildFailure(f"{label} exceeds the bounded metadata cap: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be an object")
    return value


def _regular_record(path: Path, label: str) -> dict[str, Any]:
    """Reuse V1's bounded source record without allowing payload reads."""
    return V1._record(path, label, allow_deferred_large=False, allow_payload_suffix=True)


def _record_map(request: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = request.get("input_records")
    if not isinstance(records, dict):
        raise BuildFailure("V1 request has no input_records map")
    return {str(path): value for path, value in records.items() if isinstance(value, dict)}


def _deferred_records(request: dict[str, Any]) -> list[dict[str, Any]]:
    values = request.get("deferred_input_records", [])
    if not isinstance(values, list):
        raise BuildFailure("V1 deferred_input_records is not a list")
    result = []
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("path"), str):
            raise BuildFailure("V1 deferred input record is malformed")
        result.append(dict(value))
    return result


def _storage_estimate(owner_case: dict[str, Any], candidate_dp: float) -> dict[str, Any]:
    """Make a bounded reservation estimate without calling GenCase.

    The estimate is deliberately a reservation proxy, not a predicted actual
    count.  The source audit supplies a volume and sometimes a lattice upper
    bracket; fixed particles, clip effects, and final product bytes remain
    unknown until the parent run.
    """
    owner_spec = owner_case.get("owner_spec") or {}
    projection = owner_spec.get("source_lattice_projection") or {}
    bracket = projection.get("raw_count_bracket")
    upper: float | None = None
    if isinstance(bracket, dict) and isinstance(bracket.get("upper"), (int, float)):
        upper = float(bracket["upper"])
    if upper is None:
        volume = owner_spec.get("source_primitive_volume_m3")
        if isinstance(volume, (int, float)) and float(candidate_dp) > 0:
            upper = float(volume) / float(candidate_dp) ** 3
    if upper is None or upper <= 0:
        upper = 100_000.0
    upper = max(1.0, upper)
    estimated_particles = int(max(1, round(upper)))
    estimated_bytes = int(STORAGE_FLOOR + estimated_particles * PER_PARTICLE_STORAGE_BYTES)
    estimated_bytes = min(STORAGE_CAP, max(STORAGE_FLOOR, estimated_bytes))
    return {
        "estimated_particles_upper_proxy": estimated_particles,
        "estimated_storage_bytes": estimated_bytes,
        "storage_hard_cap_bytes": STORAGE_CAP,
        "particle_bytes_proxy": PER_PARTICLE_STORAGE_BYTES,
        "floor_bytes": STORAGE_FLOOR,
        "basis": "source primitive volume or explicit lattice upper bracket; fixed boundary/product overhead is unknown",
        "actual_count_status": "PARENT_AFTER_GENCASE_REQUIRED",
        "scientific_prediction": False,
    }


def _case_identity(sid: str, grid: str) -> tuple[str, str, Path]:
    family = sid.split("-", 1)[0]
    case_id = f"{sid.replace('-', '_')}_{grid.upper()}_OWNER_GRID_GENCASE_V2"
    attempt_id = f"{sid.lower()}-{grid}-owner-grid-gencase-v2-parent-pending-001"
    root = DATA_ROOT / "families" / family / case_id / attempt_id
    return case_id, attempt_id, root


def _product_records(root: Path) -> dict[str, dict[str, Any]]:
    names = {
        "generated_xml": "generated.xml",
        "fluid_vtk": "generated_Fluid.vtk",
        "bound_vtk": "generated_Bound.vtk",
        "native_bi4": "generated.bi4",
        "gencase_receipt": "execution-receipt.json",
    }
    return {
        key: {
            "path": str(root / name),
            "sha256": None,
            "stat": None,
            "hash_status": "PARENT_AFTER_GENCASE_REQUIRED",
            "payload_read_by_builder": False,
            "scope": "deferred_generated_product",
        }
        for key, name in names.items()
    }


def _rewrite_request(
    request: dict[str, Any],
    owner_cases: dict[str, dict[str, Any]],
    wrapper_record: dict[str, Any],
    cli_record: dict[str, Any],
    source_audit_record: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    sid = str(request.get("sentinel_id")); grid = str(request.get("grid_label"))
    if sid not in TARGETS or grid not in GRIDS:
        raise BuildFailure(f"unexpected V1 request identity {sid}:{grid}")
    case_id, attempt_id, output_root = _case_identity(sid, grid)
    records = _record_map(request)
    deferred = _deferred_records(request)
    deferred_paths = {str(value["path"]) for value in deferred}
    static = {path: value for path, value in records.items() if path not in deferred_paths}
    for record, label in ((wrapper_record, "V2 producer builder"),
                          (cli_record, "official CLI convention evidence"),
                          (source_audit_record, "owner source audit evidence")):
        static.setdefault(str(record["path"]), dict(record, label=label))
    if not static:
        raise BuildFailure(f"{sid}:{grid} has no runtime-v8 static input files")
    source_binding = dict(request.get("source_binding") or {})
    candidate = source_binding.get("candidate_def")
    if not isinstance(candidate, dict) or not isinstance(candidate.get("path"), str):
        raise BuildFailure(f"{sid}:{grid} candidate binding is missing")
    candidate_path = Path(str(candidate["path"])).expanduser().absolute()
    stem = str(candidate_path.with_suffix(""))
    if not candidate_path.name.endswith("_Def.xml") or not stem.endswith("_Def"):
        raise BuildFailure(f"{sid}:{grid} candidate stem does not preserve the _Def convention")
    products = _product_records(output_root)
    owner_case = owner_cases[sid]
    estimate = _storage_estimate(owner_case, float(request.get("candidate_dp_m") or source_binding.get("candidate_dp_m") or 0.01))
    static_paths = sorted(static)
    input_sha = {path: value["sha256"] for path, value in static.items() if _valid_sha(value.get("sha256"))}
    deferred_bytes = sum(int(value.get("bytes", 0) or (value.get("stat_before") or {}).get("bytes", 0)) for value in deferred)
    request = dict(request)
    request.update({
        "schema": REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_SHARED_RUNTIME_V8_GENCASERUN_V2",
        "request_variant": REQUEST_VARIANT,
        "family_id": sid.split("-", 1)[0],
        "case_id": case_id,
        "attempt_id": attempt_id,
        "command": [str(V1.GENCASE), stem, "{attempt_root}/generated", "-save:all", "-threads:1"],
        "input_files": static_paths,
        "input_records": static,
        "input_sha256": input_sha,
        "input_hashes": input_sha,
        "deferred_input_files": sorted(deferred_paths),
        "deferred_input_records": deferred,
        "estimated_input_read_bytes": sum(int(value.get("bytes", 0)) for value in static.values()),
        "estimated_deferred_input_bytes": deferred_bytes,
        "estimated_storage_bytes": estimate["estimated_storage_bytes"],
        "max_storage_bytes": estimate["storage_hard_cap_bytes"],
        "estimated_storage_status": "BOUNDED_SOURCE_GEOMETRY_PROXY_NOT_ACTUAL_PRODUCT_SIZE",
        "estimated_peak_memory_bytes": 4 * 1024**3,
        "max_memory_bytes": 4 * 1024**3,
        "output_root": str(output_root),
        "planned_output_root": str(output_root),
        "output": {"atomic": True, "refuse_overwrite": True,
                   "root": str(output_root), "prefix": str(output_root / "generated"),
                   "products": products},
        "execution_allowed": False,
        "launch_disabled": True,
        "source_only": True,
        "gencase_only": True,
        "solver_started": False,
        "solver_launch": False,
        "gencase_launch": True,
        "bi4_read": False,
        "hdf5_read": False,
        "storage_estimate": estimate,
        "runtime_v8_contract": {
            "light_validate_identity": f"families/{request['family_id']}/{case_id}/{attempt_id}",
            "static_input_files_exclude_deferred_controls": True,
            "deferred_control_sha_stat_parent_after_reservation": True,
            "input_sha256_covers_input_files_only": True,
            "receipt_schema": "ds02.execution-receipt.v1",
            "receipt_success_fields": ["status", "returncode", "request", "request_sha256", "output_root", "input_hashes_at_launch", "input_hashes_after_run"],
        },
        "gencase_receipt_contract": {
            "schema": "ds02.execution-receipt.v1",
            "required_top_level": ["status", "returncode", "request", "request_sha256", "output_root"],
            "success": {"status": "completed", "returncode": 0},
            "output_root": str(output_root),
            "product_map_role": "gencase_receipt",
        },
        "cli_convention_evidence": {
            "status": "SOURCE_BOUND_PRIOR_COMPLETED_CASES_NO_NEW_LAUNCH",
            "input_argument": stem,
            "input_argument_rule": "candidate *_Def.xml -> path.with_suffix('') == *_Def; do not strip _Def or append _Def",
            "output_prefix": str(output_root / "generated"),
            "expected_products": ["generated.xml", "generated_Fluid.vtk", "generated_Bound.vtk", "generated.bi4", "execution-receipt.json"],
            "evidence_source": str(CLI_EVIDENCE),
        },
        "scientific_qualification": QUALIFICATION,
    })
    return request, products


def _write(path: Path, value: Any) -> None:
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing overwrite of immutable V2 output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def build(owner_report_path: Path, output_dir: Path) -> dict[str, Any]:
    owner = _read_json(owner_report_path, "owner V3 source audit")
    if owner.get("schema") != "ds02.stage2.three-sentinel.owner-grid-source-audit.v3":
        raise BuildFailure("owner report is not the frozen V3 source audit")
    owner_cases = {str(row.get("sentinel_id")): row for row in owner.get("cases", []) if isinstance(row, dict)}
    if set(owner_cases) != set(TARGETS):
        raise BuildFailure("owner report does not contain exactly the three target sentinels")
    output_dir = output_dir.expanduser().absolute()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BuildFailure(f"refusing overwrite of non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    # V1 builds the reviewed source closure and product rows.  V2 only
    # normalizes the runtime identity/closure after that immutable preparation.
    V1.build(owner_report_path, output_dir)
    request_dir = output_dir / "requests"
    wrapper_record = _regular_record(Path(__file__), "V2 producer builder")
    cli_record = _regular_record(CLI_EVIDENCE, "official CLI convention evidence")
    source_audit_record = _regular_record(SOURCE_AUDIT, "owner source audit implementation")
    request_records: dict[tuple[str, str], dict[str, Any]] = {}
    product_values: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(request_dir.glob("*-owner-grid-gencase-v1-request.json")):
        old = _read_json(path, f"V1 request {path.name}")
        new, products = _rewrite_request(old, owner_cases, wrapper_record, cli_record, source_audit_record)
        new_path = path.with_name(path.name.replace("-v1-request.json", "-v2-request.json"))
        _write(new_path, new)
        path.unlink()
        key = (str(new["sentinel_id"]), str(new["grid_label"]))
        request_records[key] = V1._record(new_path, f"V2 producer request {key[0]}:{key[1]}", allow_deferred_large=False)
        product_values[key] = products
    if len(request_records) != 9:
        raise BuildFailure(f"expected 9 rewritten requests, found {len(request_records)}")
    old_map = _read_json(output_dir / "owner-grid-gencase-product-map-v1.json", "V1 product map")
    old_manifest_path = output_dir / "owner-grid-gencase-producer-manifest-v1.json"
    products: list[dict[str, Any]] = []
    for row in old_map.get("products", []):
        key = (str(row.get("sentinel_id")), str(row.get("grid_label")))
        if key not in request_records:
            raise BuildFailure(f"V1 product row has no rewritten request: {key}")
        request_record = request_records[key]
        request_path = Path(request_record["path"])
        request = _read_json(request_path, f"rewritten request {key}")
        product = dict(product_values[key])
        product.update({"sentinel_id": key[0], "grid_label": key[1], "row_key": f"{key[0]}:{key[1]}",
                        "physical_case_id": request.get("physical_case_id"), "case_id": request["case_id"],
                        "attempt_id": request["attempt_id"], "planned_output_root": request["output_root"],
                        "producer_request": request_record, "native_header_probe": {"status": "PARENT_AFTER_GENCASE_REQUIRED", "path": str(Path(request["output_root"]) / "native-header.json")},
                        "status": "PENDING_PARENT_GUARDED_GENCASE", "scientific_qualification": QUALIFICATION})
        products.append(product)
    map_value = {
        "schema": PRODUCT_SCHEMA,
        "status": "PENDING_PARENT_GUARDED_GENCASE_V2",
        "owner_report": V1._read_json(owner_report_path, "owner V3 source audit")[1],
        "official_gencase": old_map.get("official_gencase"),
        "producer_request_count": 9,
        "products": products,
        "runtime_v8_contract": {"product_path_identity": "families/<family>/<case_id>/<attempt_id>", "receipt_schema": "ds02.execution-receipt.v1", "deferred_controls_not_in_input_files": True},
        "read_scope": {"request_builder_read_products": False, "generated_products_exist": False, "parent_after_reservation_product_sha_stat": True, "solver_launch": False, "scientific_credit": 0},
        "scientific_qualification": QUALIFICATION,
    }
    map_path = output_dir / "owner-grid-gencase-product-map-v2.json"
    _write(map_path, map_value)
    map_record = V1._record(map_path, "V2 nine-row GenCase product map", allow_deferred_large=False)
    manifest = {
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_SHARED_RUNTIME_V8_GENCASERUNS_V2",
        "owner_report": V1._read_json(owner_report_path, "owner V3 source audit")[1],
        "official_gencase": old_map.get("official_gencase"),
        "producer_requests": [request_records[(sid, grid)] | {"row_key": f"{sid}:{grid}"} for sid in TARGETS for grid in GRIDS],
        "product_map": map_record,
        "rows": products,
        "runtime_v8_contract": {"all_attempts_follow_runtime_family_case_attempt_path": True, "deferred_controls_excluded_from_input_files": True, "receipt_schema": "ds02.execution-receipt.v1"},
        "read_scope": {"source_metadata_only": True, "large_control_files_deferred": True, "generated_products_deferred": True, "gencase_launch_by_builder": False, "solver_launch": False, "scientific_credit": 0},
        "scientific_qualification": QUALIFICATION,
    }
    manifest_path = output_dir / "owner-grid-gencase-producer-manifest-v2.json"
    _write(manifest_path, manifest)
    # The V1 files were an internal staging product.  Do not leave stale V1
    # identity/product-map bytes beside the source-prepared V2 package.
    for stale in (old_manifest_path, output_dir / "owner-grid-gencase-product-map-v1.json"):
        if stale.exists():
            stale.unlink()
    return {"manifest": manifest, "manifest_path": str(manifest_path), "product_map": map_value,
            "product_map_path": str(map_path), "producer_requests": 9,
            "producer_request_paths": [str(request_records[(sid, grid)]["path"]) for sid in TARGETS for grid in GRIDS]}


def _self_test() -> None:
    assert _case_identity("F2-S2", "coarse")[2].parts[-2] == "F2_S2_COARSE_OWNER_GRID_GENCASE_V2"
    assert _case_identity("F2-S2", "coarse")[2].parts[-1].startswith("f2-s2-coarse-")
    candidate = Path("sample_Def.xml")
    assert str(candidate.with_suffix("")) == "sample_Def"
    assert str(candidate.with_suffix("")).endswith("_Def")
    products = _product_records(Path("/tmp/owner-grid-v2-attempt"))
    assert set(products) == {"generated_xml", "fluid_vtk", "bound_vtk", "native_bi4", "gencase_receipt"}
    assert products["fluid_vtk"]["path"].endswith("generated_Fluid.vtk")
    sample = {"input_records": {"small.xml": {"read_mode": "small_read"}, "forcing.csv": {"read_mode": "deferred_parent_after_reservation"}},
              "deferred_input_records": [{"path": "forcing.csv", "read_mode": "deferred_parent_after_reservation"}]}
    assert set(_record_map(sample)) == {"small.xml", "forcing.csv"}
    assert {x["path"] for x in _deferred_records(sample)} == {"forcing.csv"}
    print("PASS_THREE_SENTINEL_OWNER_GRID_GENCASE_PRODUCER_REQUEST_V2_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--owner-report", type=Path, default=V1.OWNER_REPORT_DEFAULT)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            _self_test()
        except Exception as exc:
            print(f"FAILED_THREE_SENTINEL_OWNER_GRID_GENCASE_PRODUCER_REQUEST_V2_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.output_dir is None:
        parser.error("--build requires --output-dir")
    try:
        result = build(args.owner_report, args.output_dir)
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_GENCASE_PRODUCER_REQUEST_V2: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["manifest"]["status"], "manifest": result["manifest_path"],
                      "product_map": result["product_map_path"], "producer_requests": 9,
                      "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
