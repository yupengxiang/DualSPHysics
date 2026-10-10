#!/usr/bin/env python3
"""Prepare the nine-row GenCase -> native-header initial-support handoff.

This is an additive successor to the frozen native-header request V2.  The
source-prepared GenCase product map is deliberately allowed to contain
placeholders: the nine products, their runtime receipts, and their terminal
proofs are created by a later parent reservation.  When a completed map is
supplied, this builder joins every row to the *raw producer-request file* and
to the exact proof/control records named by that row.  It never selects a
latest file by label and never hashes or parses a BI4/VTK product.

The emitted command reuses the V2 native-header worker, which in turn calls
the V3 initial-support receipt verifier.  The manifest therefore carries the
V3 support request/manifest and the V4 verifier source as explicit inputs.
Missing product/proof records remain a waiting source package; they do not
become a scientific pass.  A parent may enable the request only after the
GenCase receipt and all product pre/post guards exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
PROBE = HERE / "stage2_three_sentinel_owner_grid_native_header_probe_v2.py"
VERIFY_V3 = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v3.py"
VERIFY_V4 = HERE / "stage2_three_sentinel_owner_grid_initial_support_verify_v4.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
JSON_CAP = 10 * 1024 * 1024
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
PRODUCT_ROLES = ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4", "gencase_receipt")
PAYLOAD_SUFFIXES = {".bi4", ".vtk", ".h5", ".hdf5", ".bin", ".dat"}
SCHEMA = "ds02.stage2.three-sentinel-owner-grid-native-header-probe-manifest.v3"
REQUEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-native-header-probe-request.v3"


class BuildFailure(RuntimeError):
    pass


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _stat_from(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    source = value.get("stat") or value.get("stat_after") or value.get("stat_post") or value.get("stat_before") or {}
    aliases = {
        "device": ("device", "dev", "st_dev"),
        "inode": ("inode", "ino", "st_ino"),
        "bytes": ("bytes", "size"),
        "mtime_ns": ("mtime_ns",),
        "ctime_ns": ("ctime_ns",),
    }
    result: dict[str, int] = {}
    if isinstance(source, dict):
        for target, names in aliases.items():
            for name in names:
                if name in source:
                    result[target] = int(source[name])
                    break
    return result


def _small_record(path: Path, label: str) -> dict[str, Any]:
    """Read and hash a bounded source/JSON file, never a native product."""
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    return {
        "path": str(path), "sha256": _sha(raw), "stat": after,
        "hash_status": "BOUND_SMALL_METADATA", "read_mode": "small_read",
        "payload_read_by_builder": False,
    }


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    record = _small_record(path, label)
    try:
        value = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be an object")
    return value, record


def _metadata_record(value: Any, label: str, *, allow_absent: bool = True) -> dict[str, Any]:
    """Bind a deferred product by path/stat/SHA without reading its bytes."""
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise BuildFailure(f"{label} lacks an explicit path record")
    path = _abs(value["path"])
    if path.is_symlink():
        raise BuildFailure(f"{label} is a symlink: {path}")
    declared_sha = value.get("sha256")
    if declared_sha is not None and not _valid_sha(declared_sha):
        raise BuildFailure(f"{label} has malformed SHA")
    expected = _stat_from(value)
    if path.is_file():
        current = _stat(path)
        for field, expected_value in expected.items():
            if current[field] != expected_value:
                raise BuildFailure(f"{label} {field} differs from its declared stat")
        if path.suffix.lower() not in PAYLOAD_SUFFIXES and declared_sha is not None:
            # JSON receipts/proofs are small metadata.  Verify their raw file
            # SHA, while payload products remain strictly stat-only.
            if current["bytes"] <= JSON_CAP:
                actual = _sha(path.read_bytes())
                after = _stat(path)
                if actual.lower() != str(declared_sha).lower() or after != current:
                    raise BuildFailure(f"{label} metadata SHA/stat changed during check")
        status = "PRESENT_PARENT_METADATA_ONLY"
    else:
        if not allow_absent:
            raise BuildFailure(f"{label} is absent: {path}")
        status = "PARENT_AFTER_RESERVATION_REQUIRED"
    return {
        "path": str(path),
        "sha256": str(declared_sha).lower() if _valid_sha(declared_sha) else None,
        "stat": expected,
        "hash_status": status,
        "read_mode": "stat_only_deferred_product",
        "payload_read_by_builder": False,
    }


def _record_from_path(value: Any, label: str, *, allow_absent: bool = True) -> dict[str, Any]:
    if isinstance(value, dict) and isinstance(value.get("path"), str):
        return _metadata_record(value, label, allow_absent=allow_absent)
    if isinstance(value, str):
        path = _abs(value)
        if path.is_file():
            return _small_record(path, label)
        if allow_absent:
            return {"path": str(path), "sha256": None, "stat": {},
                    "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
                    "read_mode": "stat_only_deferred_metadata", "payload_read_by_builder": False}
    raise BuildFailure(f"{label} lacks a path record")


def _row_products(row: dict[str, Any]) -> dict[str, Any]:
    values = row.get("products")
    result = dict(values) if isinstance(values, dict) else {}
    for role in PRODUCT_ROLES:
        if role in row:
            result[role] = row[role]
    return result


def _row_record(row: dict[str, Any], role: str) -> Any:
    aliases = {
        "gencase_receipt": ("gencase_receipt", "receipt", "execution_receipt"),
        "actual_proof": ("actual_proof", "proof", "root_proof", "terminal_proof"),
        "staged_worker_report": ("staged_worker_report", "worker_report", "staged_report"),
    }
    for key in aliases.get(role, (role,)):
        if key in row and row[key] is not None:
            return row[key]
    products = row.get("products")
    if isinstance(products, dict):
        for key in aliases.get(role, (role,)):
            if key in products and products[key] is not None:
                return products[key]
    return None


def _iter_record_values(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("path"), str):
            yield "record", value
        else:
            for key, item in value.items():
                for nested_key, nested_value in _iter_record_values(item):
                    yield f"{key}.{nested_key}", nested_value
    elif isinstance(value, list):
        for item in value:
            yield from _iter_record_values(item)


def _proof_or_report(value: Any, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return _record_from_path(value, label, allow_absent=True)


def _write_once(path: Path, value: Any) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _validate_initial(initial: dict[str, Any]) -> list[dict[str, Any]]:
    cases = initial.get("cases")
    if not isinstance(cases, list):
        raise BuildFailure("initial-support manifest lacks cases")
    rows = {(str(row.get("sentinel_id")), str(row.get("grid_label"))): row for row in cases if isinstance(row, dict)}
    if set(rows) != set((sid, grid) for sid in TARGETS for grid in GRIDS):
        raise BuildFailure("initial-support manifest does not cover exactly nine rows")
    return [rows[(sid, grid)] for sid in TARGETS for grid in GRIDS]


def build(initial_manifest_path: Path, initial_request_path: Path | None,
          product_map_path: Path, decoder_path: Path, output_dir: Path,
          admission_manifest_path: Path | None = None) -> dict[str, Any]:
    initial, initial_record = _read_json(initial_manifest_path, "initial-support V3 manifest")
    if initial.get("schema") != "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1":
        raise BuildFailure("initial-support manifest is not the V3-compatible schema")
    initial_rows = _validate_initial(initial)
    initial_request_record = None
    if initial_request_path is not None:
        initial_request_record = _small_record(initial_request_path, "initial-support V3 request")
    admission_record = None
    if admission_manifest_path is not None:
        admission_record = _small_record(admission_manifest_path, "GenCase admission manifest")
    product_map, product_map_record = _read_json(product_map_path, "nine-row GenCase product map")
    products = product_map.get("products", product_map.get("rows"))
    if not isinstance(products, list):
        raise BuildFailure("product map lacks products/rows")
    product_rows = {(str(row.get("sentinel_id")), str(row.get("grid_label"))): row for row in products if isinstance(row, dict)}
    if set(product_rows) != set((sid, grid) for sid in TARGETS for grid in GRIDS):
        raise BuildFailure("product map does not cover exactly nine rows")
    decoder_record = _small_record(decoder_path, "official BI4 decoder")
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BuildFailure(f"refusing non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    static: dict[str, dict[str, Any]] = {
        initial_record["path"]: initial_record,
        product_map_record["path"]: product_map_record,
        str(PROBE): _small_record(PROBE, "native-header probe worker"),
        str(VERIFY_V3): _small_record(VERIFY_V3, "initial-support V3 verifier"),
        str(VERIFY_V4): _small_record(VERIFY_V4, "initial-support V4 runtime verifier"),
        decoder_record["path"]: decoder_record,
    }
    if initial_request_record:
        static[initial_request_record["path"]] = initial_request_record
    if admission_record:
        static[admission_record["path"]] = admission_record

    actual_rows = 0
    proof_rows = 0
    for initial_row in initial_rows:
        sid, grid = str(initial_row["sentinel_id"]), str(initial_row["grid_label"])
        key = f"{sid}:{grid}"
        row = product_rows[(sid, grid)]
        producer = row.get("producer_request")
        if not isinstance(producer, dict) or not isinstance(producer.get("path"), str):
            raise BuildFailure(f"{key} lacks exact producer_request path")
        producer_path = _abs(producer["path"])
        producer_record = _small_record(producer_path, f"{key} producer request")
        if _valid_sha(producer.get("sha256")) and producer_record["sha256"].lower() != str(producer["sha256"]).lower():
            raise BuildFailure(f"{key} producer request SHA differs from product map")
        static[producer_record["path"]] = producer_record

        product_values = _row_products(row)
        product_records: dict[str, dict[str, Any]] = {}
        for role in PRODUCT_ROLES:
            source = product_values.get(role)
            if source is None:
                # Preserve the official output convention when a source map
                # only records its output root/prefix.
                output_root = row.get("output_root") or row.get("planned_output_root")
                if isinstance(output_root, str):
                    names = {"generated_xml": "generated.xml", "fluid_vtk": "generated_Fluid.vtk",
                             "bound_vtk": "generated_Bound.vtk", "native_bi4": "generated.bi4",
                             "gencase_receipt": "execution-receipt.json"}
                    source = {"path": str(_abs(Path(output_root) / names[role])), "sha256": None, "stat": {}}
            if source is None:
                raise BuildFailure(f"{key} missing product role {role}")
            rec = _metadata_record(source, f"{key} {role}")
            product_records[role] = rec
            deferred.append({"row_key": key, "role": role, **rec})

        proof = _proof_or_report(_row_record(row, "actual_proof"), f"{key} actual proof")
        worker_report = _proof_or_report(_row_record(row, "staged_worker_report"), f"{key} staged worker report")
        if proof is not None:
            proof_rows += 1
            static[proof["path"]] = proof
        if worker_report is not None:
            static[worker_report["path"]] = worker_report

        control_records: list[dict[str, Any]] = []
        for name, value in _iter_record_values(row.get("control_closure") or row.get("control") or {}):
            # Auxiliary controls can be large CSV/asset payloads.  Bind their
            # declared path/stat/SHA without reading their contents here.
            record = _metadata_record(value, f"{key} control closure {name}")
            control_records.append(record)
            static[record["path"]] = record

        status = str(row.get("status") or product_map.get("status") or "PENDING")
        products_present = all(rec["hash_status"] == "PRESENT_PARENT_METADATA_ONLY" for rec in product_records.values())
        if products_present and proof is not None:
            actual_rows += 1
        cases.append({
            "row_key": key, "sentinel_id": sid, "grid_label": grid,
            "family_id": row.get("family_id", sid.split("-", 1)[0]),
            "physical_case_id": row.get("physical_case_id"),
            "producer_request": producer_record,
            "gencase_receipt": product_records["gencase_receipt"],
            "native_bi4": product_records["native_bi4"],
            "generated_xml": product_records["generated_xml"],
            "fluid_vtk": product_records["fluid_vtk"],
            "bound_vtk": product_records["bound_vtk"],
            "actual_proof": proof,
            "staged_worker_report": worker_report,
            "control_closure": control_records,
            "actual_control_cwd": row.get("actual_control_cwd"),
            "decoder": decoder_record,
            "candidate_def": row.get("candidate_def"),
            "source_xml": row.get("source_xml"),
            "status": status,
            "native_header_probe": {"status": "PARENT_AFTER_RESERVATION_REQUIRED"},
            "position_only_initial_support": True,
            "velocity_rhop_mass_missing_are_unknown": True,
        })

    manifest = {
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE" if actual_rows == 9 else "WAITING_NINE_GENCASE_ACTUAL_PRODUCTS_AND_PROOFS",
        "initial_support_manifest": initial_record,
        "initial_support_request": initial_request_record,
        "initial_support_verifier": {"v3": str(VERIFY_V3), "v4": str(VERIFY_V4)},
        "product_map": product_map_record,
        "producer_requests": [case["producer_request"] for case in cases],
        "cases": cases,
        "decoder": decoder_record,
        "proof_rows": proof_rows,
        "actual_rows_with_all_product_metadata": actual_rows,
        "native_deferred_policy": {
            "product_count": 45, "parent_after_reservation_first_sha_and_stat": True,
            "post_decode_sha_and_stat": True, "payload_read_by_builder": False,
            "xml_mass_fallback": False, "position_only_initial_support": True,
            "missing_velocity_rhop_mass": "UNKNOWN_NOT_EXPOSED_BY_INITIAL_DECODER",
        },
        "read_scope": {
            "production_payload_read_by_builder": False,
            "production_bi4_vtk_hdf5_read": False, "solver_launch": False,
            "gencase_launch": False, "scientific_credit": 0,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }
    manifest_path = output_dir / "native-header-probe-manifest-v3.json"
    _write_once(manifest_path, manifest)
    manifest_record = _small_record(manifest_path, "native-header V3 manifest")
    static[manifest_record["path"]] = manifest_record
    request = {
        "schema": "ds02.request.v1", "variant_schema": REQUEST_SCHEMA,
        "status": manifest["status"], "kind": "generic-cpu-audit",
        "cpu_task_kind": "initial_support_native_header_probe", "family_id": "DS02-THREE-SENTINEL",
        "case_id": "F2_F3_F5_OWNER_GRID_NATIVE_HEADER_PROBE_V3",
        "attempt_id": "PARENT_ASSIGNED_AFTER_NINE_GENCASE",
        "command": [str(PYTHON), str(PROBE), "--run", "--manifest", manifest_record["path"],
                    "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/report/native-header-probe-v3.json"],
        "input_files": sorted(static), "input_records": static,
        "input_sha256": {path: rec["sha256"] for path, rec in static.items() if _valid_sha(rec.get("sha256"))},
        "manifest": manifest_record, "deferred_input_records": deferred,
        "deferred_input_files": sorted({item["path"] for item in deferred}),
        "execution_allowed": False, "gencase_launch": False, "solver_launch": False,
        "parent_v8_deferred_fields_not_credit": True,
        "resource_scope": {"cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800,
                           "memory_max_bytes": 4 * 1024**3, "scratch_max_bytes": 256 * 1024**2,
                           "log_max_bytes": 64 * 1024, "estimated_storage_bytes": 256 * 1024**2, "gpu": "none"},
        "source_binding": {
            "producer_request_exact_raw_file_sha": True,
            "actual_proof_exact_raw_file_sha_when_present": True,
            "control_closure_pre_post_stat": True,
            "native_products_pre_post_sha_stat_parent": True,
            "initial_support_request_v3_and_verifier_v4_bound": True,
            "xml_mass_fallback": False, "position_only_initial_support": True,
            "velocity_rhop_mass_unknown_if_decoder_omits": True,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "launch_disabled": True, "native_payload_read": False, "ledger_mutation": False,
    }
    request_path = output_dir / "native-header-probe-request-v3.json"
    _write_once(request_path, request)
    return {"manifest": str(manifest_path), "request": str(request_path), "status": manifest["status"],
            "actual_rows": actual_rows, "proof_rows": proof_rows, "production_payload_read": False}


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="owner-grid-native-header-request-v3-") as td:
        root = Path(td)
        # Nine source-prepared rows: product payloads are intentionally absent
        # and therefore remain parent-deferred.  Producer requests are real
        # small JSON files, so raw request SHA joining is exercised.
        initial_cases: list[dict[str, Any]] = []
        product_rows: list[dict[str, Any]] = []
        for sid in TARGETS:
            for grid in GRIDS:
                key = f"{sid}:{grid}"
                producer_path = root / "producer" / f"{sid.replace('-', '_')}_{grid}.json"
                producer_path.parent.mkdir(parents=True, exist_ok=True)
                producer = {"schema": "ds02.request.v1", "family_id": sid.split("-", 1)[0],
                            "case_id": f"{sid}_{grid}", "attempt_id": f"{sid}_{grid}_attempt",
                            "kind": "cpu", "cpu_task_kind": "gencase", "execution_allowed": False}
                producer_path.write_text(json.dumps(producer, sort_keys=True) + "\n", encoding="utf-8")
                output_root = root / "future" / sid / grid / "attempt"
                initial_cases.append({"sentinel_id": sid, "grid_label": grid,
                                     "family_id": sid.split("-", 1)[0], "physical_case_id": key})
                products = {role: {"path": str(output_root / name), "sha256": None, "stat": {}}
                            for role, name in {"generated_xml": "generated.xml", "fluid_vtk": "generated_Fluid.vtk",
                                               "bound_vtk": "generated_Bound.vtk", "native_bi4": "generated.bi4",
                                               "gencase_receipt": "execution-receipt.json"}.items()}
                product_rows.append({"sentinel_id": sid, "grid_label": grid,
                                     "producer_request": {"path": str(producer_path), "sha256": _sha(producer_path.read_bytes())},
                                     "products": products, "status": "PENDING_PARENT_GUARDED_GENCASE"})
        initial_path = root / "initial.json"
        initial_path.write_text(json.dumps({"schema": "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1",
                                            "cases": initial_cases}) + "\n", encoding="utf-8")
        map_path = root / "product-map.json"
        map_path.write_text(json.dumps({"schema": "ds02.stage2.root-nine-gencase-product-map.v2", "products": product_rows}) + "\n", encoding="utf-8")
        decoder = root / "bi4_dump"; decoder.write_bytes(b"tiny-decoder")
        result = build(initial_path, None, map_path, decoder, root / "out")
        assert result["status"] == "WAITING_NINE_GENCASE_ACTUAL_PRODUCTS_AND_PROOFS"
        request = json.loads(Path(result["request"]).read_text(encoding="utf-8"))
        assert len(request["deferred_input_records"]) == 45
        assert request["execution_allowed"] is False and request["native_payload_read"] is False
        # Rehearse the actual completed-map shape with tiny manufactured
        # products.  Product bytes are only stat-checked by this builder;
        # proof and producer request JSON are joined by their raw file SHA.
        def fixture_record(path: Path, *, payload: bool = False) -> dict[str, Any]:
            raw = path.read_bytes()
            return {"path": str(path), "sha256": _sha(raw), "stat": _stat(path),
                    "scope": "fixture_payload" if payload else "fixture_metadata"}
        actual_rows: list[dict[str, Any]] = []
        for row in product_rows:
            sid, grid = str(row["sentinel_id"]), str(row["grid_label"])
            output_root = Path(row["products"]["native_bi4"]["path"]).parent
            output_root.mkdir(parents=True, exist_ok=True)
            names = {"generated_xml": "generated.xml", "fluid_vtk": "generated_Fluid.vtk",
                     "bound_vtk": "generated_Bound.vtk", "native_bi4": "generated.bi4",
                     "gencase_receipt": "execution-receipt.json"}
            products = {}
            for role, name in names.items():
                path = output_root / name
                path.write_bytes((role + "-fixture\n").encode("utf-8"))
                products[role] = fixture_record(path, payload=role != "gencase_receipt")
            proof_path = root / "proofs" / f"{sid.replace('-', '_')}_{grid}.json"
            proof_path.parent.mkdir(parents=True, exist_ok=True)
            proof_path.write_text(json.dumps({"status": "VERIFIED_ACTUAL_GENCASE_FIXTURE", "row_key": f"{sid}:{grid}"}) + "\n", encoding="utf-8")
            control_path = root / "control" / f"{sid.replace('-', '_')}_{grid}.csv"
            control_path.parent.mkdir(parents=True, exist_ok=True)
            control_path.write_text("time,forcing\n0,0\n", encoding="utf-8")
            actual_rows.append({**row, "status": "COMPLETED", "products": products,
                               "actual_proof": fixture_record(proof_path),
                               "control_closure": {"forcing": fixture_record(control_path)}})
        actual_map = root / "actual-product-map.json"
        actual_map.write_text(json.dumps({"schema": "ds02.stage2.root-nine-gencase-product-map.v2",
                                          "status": "COMPLETED", "products": actual_rows}) + "\n", encoding="utf-8")
        actual_result = build(initial_path, None, actual_map, decoder, root / "out-actual")
        assert actual_result["status"] == "READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE"
        assert actual_result["actual_rows"] == 9 and actual_result["proof_rows"] == 9
        actual_request = json.loads(Path(actual_result["request"]).read_text(encoding="utf-8"))
        assert len(actual_request["deferred_input_records"]) == 45
        assert len(actual_request["input_files"]) >= 27  # nine producer + nine proof + nine controls + code
        # A producer request byte mutation is rejected even though the
        # product files themselves remain untouched.
        producer = Path(actual_rows[0]["producer_request"]["path"])
        producer.write_text(producer.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
        try:
            build(initial_path, None, actual_map, decoder, root / "out2")
        except BuildFailure:
            pass
        else:
            raise AssertionError("producer request byte mutation was accepted")
    print("PASS_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_REQUEST_V3_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--initial-manifest", type=Path)
    parser.add_argument("--initial-request", type=Path)
    parser.add_argument("--product-map", type=Path, required=False)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--admission-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        required = (args.initial_manifest, args.product_map, args.decoder, args.output_dir)
        if any(value is None for value in required):
            parser.error("--build requires --initial-manifest, --product-map, --decoder, and --output-dir")
        result = build(args.initial_manifest, args.initial_request, args.product_map, args.decoder,
                       args.output_dir, args.admission_manifest)
        print(json.dumps({"status": result["status"], "manifest": result["manifest"],
                          "request": result["request"], "actual_rows": result["actual_rows"],
                          "proof_rows": result["proof_rows"], "scientific_credit": 0,
                          "production_payload_read": False}, sort_keys=True))
        return 0
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_NATIVE_HEADER_PROBE_REQUEST_V3: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
