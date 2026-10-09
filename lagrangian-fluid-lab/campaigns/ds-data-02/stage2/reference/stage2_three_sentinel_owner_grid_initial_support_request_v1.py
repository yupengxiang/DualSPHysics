#!/usr/bin/env python3
"""Build source-bound requests for nine GenCase-only initial-support rows.

The owner-grid V3 report supplies the source XML/Def, candidate Def, receipt,
owner predicate, and frozen source evidence.  A small product map supplies
the *expected* generated.xml/Fluid.vtk/Bound.vtk/BI4/receipt paths for each
of the three grids.  Product files are stat-only deferred inputs; this builder
never opens them and never starts GenCase or a solver.  The parent may run the
official GenCase commands separately and then bind the same manifest to the
guarded initial-support worker.
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
WORKER = HERE / "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py"
VERIFIER = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v1.py"
GEOMETRY = HERE / "stage2_four_sentinel_gencase_geometry_support_audit_v1.py"
SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1"
REQUEST_SCHEMA = "ds02.request.v1"
WORKER_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-audit.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}
SMALL_CAP = 16 * 1024 * 1024
PAYLOAD_SUFFIXES = {".bi4", ".vtk", ".vtu", ".h5", ".hdf5", ".part", ".hdf"}
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"


class BuildFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _regular(path: Path, label: str) -> Path:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _read_json(path: Path, label: str, *, cap: int = SMALL_CAP) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > cap:
        raise BuildFailure(f"{label} exceeds bounded source cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise BuildFailure(f"{label} changed while read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                   "stat": after, "payload_read_by_builder": True,
                   "scope": "bounded_source_metadata"}


def _record(path: Path, label: str, *, read: bool = True) -> dict[str, Any]:
    path = _regular(path, label)
    before = _stat(path)
    if read and before["bytes"] > SMALL_CAP:
        raise BuildFailure(f"{label} exceeds bounded source cap: {path}")
    digest = None
    if read:
        raw = path.read_bytes()
        after = _stat(path)
        if before != after or len(raw) != before["bytes"]:
            raise BuildFailure(f"{label} changed while read: {path}")
        digest = hashlib.sha256(raw).hexdigest()
    return {"path": str(path), "sha256": digest, "stat": before,
            "hash_status": "BOUND_SMALL_SOURCE" if read else "PARENT_AFTER_RESERVATION_REQUIRED",
            "payload_read_by_builder": bool(read),
            "scope": "bounded_source_metadata" if read else "deferred_parent_product"}


def _record_from_owner(value: Any, label: str, *, allow_deferred: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise BuildFailure(f"{label} record lacks path")
    path = _absolute(Path(value["path"]))
    if path.suffix.lower() in PAYLOAD_SUFFIXES and not allow_deferred:
        raise BuildFailure(f"{label} is a payload and cannot be a static source: {path}")
    declared = value.get("sha256")
    if path.is_file() and not path.is_symlink():
        if path.suffix.lower() in PAYLOAD_SUFFIXES:
            # A forcing file may be large.  It is deferred by the parent even
            # when the owner report contains only a path/stat record.
            return _record(path, label, read=False)
        return _record(path, label, read=True)
    if not allow_deferred:
        raise BuildFailure(f"{label} is absent: {path}")
    stat = value.get("stat") or value.get("stat_after") or {}
    return {"path": str(path), "sha256": declared if isinstance(declared, str) and len(declared) == 64 else None,
            "stat": stat, "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
            "payload_read_by_builder": False, "scope": "deferred_parent_product"}


def _literal_python() -> dict[str, Any]:
    if not PYTHON.is_symlink() or not PYTHON.exists():
        raise BuildFailure(f"literal venv interpreter is unavailable: {PYTHON}")
    target = PYTHON.resolve()
    if not target.is_file() or not PYVENV.is_file():
        raise BuildFailure("literal venv target or pyvenv.cfg is unavailable")
    target_record = _record(target, "resolved venv interpreter")
    return {"literal_argv0": str(PYTHON), "resolved_target": str(target),
            "resolved_target_sha256": target_record["sha256"],
            "target_record": target_record,
            "pyvenv": _record(PYVENV, "pyvenv.cfg")}


def _case_rows(owner: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if owner.get("schema") != "ds02.stage2.three-sentinel.owner-grid-source-audit.v3":
        raise BuildFailure("owner report schema must be the frozen V3 source audit")
    rows = owner.get("cases")
    if not isinstance(rows, list):
        raise BuildFailure("owner report has no cases list")
    result = {str(row.get("sentinel_id")): row for row in rows if isinstance(row, dict)}
    if set(result) != set(TARGETS):
        raise BuildFailure(f"owner report must contain {TARGETS}")
    return result


def _source_request_rows(case: dict[str, Any], sid: str) -> dict[str, dict[str, Any]]:
    requests = case.get("source_requests")
    if not isinstance(requests, list):
        raise BuildFailure(f"{sid} owner report has no source_requests")
    result: dict[str, dict[str, Any]] = {}
    for item in requests:
        if not isinstance(item, dict) or item.get("grid_label") not in GRIDS:
            continue
        label = str(item["grid_label"])
        if label in result:
            raise BuildFailure(f"{sid} duplicate owner source request {label}")
        result[label] = item
    if set(result) != set(GRIDS):
        raise BuildFailure(f"{sid} owner report must contain original/coarse/fine source requests")
    return result


def _product_rows(product: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = product.get("products", product.get("cases"))
    if not isinstance(values, list):
        raise BuildFailure("product map needs a products list")
    result: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, dict) or item.get("sentinel_id") not in TARGETS or item.get("grid_label") not in GRIDS:
            raise BuildFailure("product map has an invalid sentinel/grid")
        key = f"{item['sentinel_id']}:{item['grid_label']}"
        if key in result:
            raise BuildFailure(f"duplicate product map row {key}")
        result[key] = item
    if set(result) != set(ROW_KEYS):
        raise BuildFailure("product map must contain exactly nine rows")
    return result


def _product_record(row: dict[str, Any], key: str, name: str) -> dict[str, Any]:
    value = row.get(name)
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise BuildFailure(f"{key} product map lacks {name}")
    path = _absolute(Path(value["path"]))
    if not path.suffix.lower() in PAYLOAD_SUFFIXES and name not in {"generated_xml", "gencase_receipt", "native_header_probe"}:
        raise BuildFailure(f"{key} {name} path is not a recognized deferred product: {path}")
    if path.is_file() and not path.is_symlink():
        return _record(path, f"{key} {name}", read=False)
    return {"path": str(path), "sha256": value.get("sha256") if isinstance(value.get("sha256"), str) else None,
            "stat": value.get("stat") or value.get("stat_after") or {},
            "hash_status": "PARENT_AFTER_GENCASE_REQUIRED", "payload_read_by_builder": False,
            "scope": "deferred_parent_gencase_product"}


def build(owner_report_path: Path, product_map_path: Path, output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    owner, owner_record = _read_json(owner_report_path, "owner-grid V3 report")
    products, products_record = _read_json(product_map_path, "nine-product map")
    owners = _case_rows(owner); product_rows = _product_rows(products)
    output_dir = _absolute(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    static: dict[str, dict[str, Any]] = {owner_record["path"]: owner_record, products_record["path"]: products_record}
    static[str(WORKER)] = _record(WORKER, "initial-support worker")
    static[ str(VERIFIER) ] = _record(VERIFIER, "initial-support verifier")
    static[ str(GEOMETRY) ] = _record(GEOMETRY, "geometry parser dependency")
    runtime = _literal_python()
    static[runtime["pyvenv"]["path"]] = runtime["pyvenv"]
    static[runtime["resolved_target"]] = dict(runtime["target_record"], scope="resolved_runtime")
    cases: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for sid in TARGETS:
        owner_case = owners[sid]; source_requests = _source_request_rows(owner_case, sid)
        source_bindings = owner_case.get("source_bindings") or {}
        source_xml = _record_from_owner(source_bindings.get("source_xml"), f"{sid} source XML")
        source_def = _record_from_owner(source_bindings.get("source_def"), f"{sid} source Def")
        source_receipt = _record_from_owner(source_bindings.get("source_receipt"), f"{sid} source receipt")
        static.update({source_xml["path"]: source_xml, source_def["path"]: source_def, source_receipt["path"]: source_receipt})
        owner_predicate = owner_case.get("owner_spec", {}).get("source_region_predicate") or {"status": "UNKNOWN"}
        owner_predicate = dict(owner_predicate, mass_rescale=False,
                               target_mass_kg=None if sid != "F2-S2" else owner_case.get("owner_spec", {}).get("owner_mass_kg"))
        for grid in GRIDS:
            key = f"{sid}:{grid}"; source = source_requests[grid]; inputs = source.get("source_inputs") or {}
            candidate_def = _record_from_owner(inputs.get("candidate_def"), f"{key} candidate Def")
            static[candidate_def["path"]] = candidate_def
            aux = inputs.get("motion_or_forcing")
            if isinstance(aux, dict) and isinstance(aux.get("path"), str):
                aux_record = _record_from_owner(aux, f"{key} motion/forcing", allow_deferred=True)
                if aux_record.get("hash_status") != "BOUND_SMALL_SOURCE":
                    deferred.append({"row_key": key, "role": "motion_or_forcing", **aux_record})
                else:
                    static[aux_record["path"]] = aux_record
            else:
                aux_record = None
            product = product_rows[key]
            product_records = {name: _product_record(product, key, name) for name in ("generated_xml", "gencase_receipt", "fluid_vtk", "bound_vtk", "native_bi4")}
            probe = product.get("native_header_probe")
            probe_record = _product_record(product, key, "native_header_probe") if isinstance(probe, dict) and isinstance(probe.get("path"), str) else {"status": "NOT_BOUND", "path": str(output_dir / f"{key.replace(':', '_')}.native-header.json")}
            for name, record in product_records.items():
                deferred.append({"row_key": key, "role": name, **record})
            if probe_record.get("status") != "NOT_BOUND":
                deferred.append({"row_key": key, "role": "native_header_probe", **probe_record})
            cases.append({"sentinel_id": sid, "grid_label": grid,
                          "family_id": owner_case.get("family_id", sid[:2]),
                          "physical_case_id": owner_case.get("physical_case_id"),
                          "source_xml": source_xml, "source_def": source_def,
                          "candidate_def": candidate_def, "source_receipt": source_receipt,
                          "motion_or_forcing": aux_record, "owner_predicate": owner_predicate,
                          **product_records, "native_header_probe": probe_record,
                          "gencase_only": {"command": ["GenCase_linux64", str(Path(candidate_def["path"]).with_suffix("")), "-threads:1"],
                                           "stem_without_xml": True, "launch_by_worker": False},
                          "scientific_qualification": QUALIFICATION})
    manifest = {"schema": SCHEMA, "status": "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT",
                "generated_by": {"builder": str(_absolute(Path(__file__))), "production_payload_read": False,
                                 "gencase_launch": False, "solver_launch": False},
                "owner_report": owner_record, "product_map": products_record,
                "cases": cases, "static_sources": list(static.values()), "deferred_input_records": deferred,
                "scientific_scope": {"neighbor_grid_truth": False, "mass_rescale": False,
                                     "xml_mass_is_not_native_mass": True, "continuous_owner": "UNKNOWN",
                                     "scientific_credit": 0}}
    manifest_path = output_dir / "owner-grid-initial-support-manifest-v1.json"
    request_path = output_dir / "owner-grid-initial-support-request-v1.json"
    if manifest_path.exists() or request_path.exists():
        raise BuildFailure("refusing overwrite immutable request outputs")
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    manifest_path.write_bytes(manifest_bytes)
    manifest_record = _record(manifest_path, "generated support manifest")
    static[manifest_record["path"]] = manifest_record
    input_files = sorted(static)
    input_sha256 = {path: static[path]["sha256"] for path in input_files if isinstance(static[path].get("sha256"), str)}
    request = {"schema": REQUEST_SCHEMA, "variant_schema": WORKER_SCHEMA,
               "status": "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT",
               "kind": "generic-cpu-audit", "cpu_task_kind": "initial_support_audit",
               "request_id": "three-sentinel-owner-grid-initial-support-v1-prepared-001",
               "family_id": "DS02-THREE-SENTINEL", "sentinel_ids": list(TARGETS),
               "case_id": "F2_F3_F5_OWNER_GRID_INITIAL_SUPPORT_V1",
               "attempt_id": "PARENT_ASSIGNED_AFTER_GENCASE",
               "command": [runtime["literal_argv0"], str(WORKER), "--run", "--manifest", str(manifest_path),
                            "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/report/owner-grid-initial-support-v1.json"],
               "input_files": input_files, "input_sha256": input_sha256,
               "input_records": static, "manifest": manifest_record,
               "deferred_input_records": deferred,
               "parent_wrapper_required": True, "parent_v8_deferred_fields_not_credit": True,
               "execution_allowed": False, "gencase_launch": False, "solver_launch": False,
               "resource_scope": {"cpu_threads": 1, "memory_max_bytes": 4 * 1024**3,
                                  "max_wall_seconds": 1800, "scratch_max_bytes": 1024**3, "gpu": "none"},
               "read_scope": {"builder_source_only": True, "worker_reads_generated_vtk_bi4_after_reservation": True,
                              "worker_reads_native_header_probe_if_bound": True, "gencase_launch": False,
                              "solver_launch": False, "neighbor_grid_truth": False},
               "scientific_qualification": QUALIFICATION}
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest, request


def _fixture_owner(root: Path) -> tuple[Path, Path]:
    import tempfile
    # Build the source report shape used by the frozen V3 worker.
    root.mkdir(parents=True, exist_ok=True); xml = root / "source.xml"; xml.write_text("<case/>", encoding="utf-8")
    receipt = root / "receipt.json"; receipt.write_text('{"status":"completed","returncode":0}\n', encoding="utf-8")
    def rec(path: Path) -> dict[str, Any]:
        st = _stat(path); return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "stat_after": st}
    requests = []
    for grid, dp in (("original", "0.1"), ("coarse", "0.05"), ("fine", "0.025")):
        candidate = root / f"{grid}_Def.xml"; candidate.write_text(f"<case><definition dp=\"{dp}\"/></case>", encoding="utf-8")
        requests.append({"grid_label": grid, "source_inputs": {"candidate_def": rec(candidate), "motion_or_forcing": None}})
    owner = {"schema": "ds02.stage2.three-sentinel.owner-grid-source-audit.v3", "status": "COMPLETE_SOURCE_OWNER_GRID_AUDIT_V3_NO_SCIENTIFIC_Q",
             "cases": [{"sentinel_id": sid, "family_id": sid[:2], "physical_case_id": f"fixture-{sid}",
                         "source_bindings": {"source_xml": rec(xml), "source_def": rec(xml), "source_receipt": rec(receipt)},
                         "owner_spec": {"source_region_predicate": {"status": "UNKNOWN"}, "owner_mass_kg": None},
                         "source_requests": requests} for sid in TARGETS]}
    owner_path = root / "owner.json"; owner_path.write_text(json.dumps(owner), encoding="utf-8")
    products = []
    for sid in TARGETS:
        for grid in GRIDS:
            d = root / sid / grid; d.mkdir(parents=True, exist_ok=True)
            products.append({"sentinel_id": sid, "grid_label": grid,
                             "generated_xml": {"path": str(d / "generated.xml")},
                             "gencase_receipt": {"path": str(d / "receipt.json")},
                             "fluid_vtk": {"path": str(d / "Fluid.vtk")},
                             "bound_vtk": {"path": str(d / "Bound.vtk")},
                             "native_bi4": {"path": str(d / "generated.bi4")}})
    product_path = root / "products.json"; product_path.write_text(json.dumps({"products": products}), encoding="utf-8")
    return owner_path, product_path


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="owner-grid-request-") as value:
        root = Path(value); owner, products = _fixture_owner(root); output = root / "out"
        global PYTHON, PYVENV
        old_python, old_pyvenv = PYTHON, PYVENV
        fake = root / "venv" / "bin" / "python"; fake.parent.mkdir(parents=True); fake.write_text("#!/usr/bin/env python3\n", encoding="utf-8"); fake.chmod(0o755)
        target = fake.parent / "python3"; target.write_text("#!/usr/bin/env python3\n", encoding="utf-8"); target.chmod(0o755)
        fake.unlink(); fake.symlink_to(target); cfg = fake.parent.parent / "pyvenv.cfg"; cfg.write_text("home=/usr/bin\n", encoding="utf-8")
        PYTHON, PYVENV = fake, cfg
        manifest, request = build(owner, products, output)
        assert len(manifest["cases"]) == 9 and len(request["deferred_input_records"]) == 45
        assert request["execution_allowed"] is False and request["gencase_launch"] is False
        assert all(item["path"] not in request["input_files"] for item in request["deferred_input_records"])
        PYTHON, PYVENV = old_python, old_pyvenv
    print("PASS_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_REQUEST_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--owner-report", type=Path)
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test(); return 0
    if args.owner_report is None or args.product_map is None or args.output_dir is None:
        parser.error("--owner-report, --product-map and --output-dir are required")
    try:
        manifest, request = build(args.owner_report, args.product_map, args.output_dir)
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_REQUEST: {exc}", file=sys.stderr); return 2
    print(json.dumps({"status": request["status"], "manifest": str(args.output_dir / "owner-grid-initial-support-manifest-v1.json"),
                      "request": str(args.output_dir / "owner-grid-initial-support-request-v1.json"),
                      "cases": len(manifest["cases"]), "scientific_credit": 0}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
