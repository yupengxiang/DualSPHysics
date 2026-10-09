#!/usr/bin/env python3
"""Independent verifier for the nine-row owner-grid initial-support audit.

The verifier reads only the manifest, request/report JSON, and stat metadata.
It does not reopen Fluid/Bound VTK, BI4, HDF5, or decoder payloads.  It checks
that the worker's complete pre/post guards and optional native-header probe
join the exact deferred paths, that all nine rows remain represented, and
that no XML mass or owner target has been promoted into scientific credit.
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
WORKER_PATH = HERE / "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py"
SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-verifier.v1"
WORKER_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-audit.v1"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
UNKNOWN = "UNKNOWN"
QUALIFICATION = {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0}
STAT_FIELDS = ("device", "inode", "bytes", "mtime_ns", "ctime_ns")
SMALL_CAP = 16 * 1024 * 1024


class VerifyFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular non-symlink file")
    before = _stat(path)
    if before["bytes"] > SMALL_CAP:
        raise VerifyFailure(f"{label} exceeds bounded JSON cap")
    raw = path.read_bytes(); after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise VerifyFailure(f"{label} changed during read")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} is not an object")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "stat": after}


def _expected(record: Any) -> dict[str, int]:
    if not isinstance(record, dict):
        return {}
    # Worker guards pass the stat object itself; manifest/source records wrap
    # it under stat/stat_after.  Accept both shapes without weakening the
    # five-field check below.
    source = (record.get("stat_post") or record.get("stat_after") or
              record.get("stat") or record)
    aliases = {"device": ("device", "dev", "st_dev"), "inode": ("inode", "ino", "st_ino"),
               "bytes": ("bytes", "size"), "mtime_ns": ("mtime_ns",), "ctime_ns": ("ctime_ns",)}
    result: dict[str, int] = {}
    for key, names in aliases.items():
        for name in names:
            if name in source:
                result[key] = int(source[name]); break
    return result


def _path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise VerifyFailure(f"{label} path is missing")
    return str(_absolute(Path(value)))


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise VerifyFailure(f"{label} is not a concrete SHA-256 digest")
    return value.lower()


def _current_stat(path: str, expected: dict[str, int], label: str) -> None:
    actual = _stat(Path(path))
    for key, value in expected.items():
        if actual.get(key) != value:
            raise VerifyFailure(f"{label} current {key} differs from report")


def _guard(record: Any, manifest_record: Any, label: str, *, payload: bool) -> None:
    if not isinstance(record, dict):
        raise VerifyFailure(f"{label} guard is missing")
    observed_path = _path(record.get("path"), f"{label} guard")
    expected_path = _path(manifest_record.get("path"), f"{label} manifest")
    if observed_path != expected_path:
        raise VerifyFailure(f"{label} guard path differs from manifest")
    pre = _expected(record.get("stat_pre")); post = _expected(record.get("stat_post"))
    if set(pre) != set(STAT_FIELDS) or pre != post:
        raise VerifyFailure(f"{label} pre/post stat is incomplete or changed")
    if record.get("stable") is not True or record.get("complete_payload_passes") != 2:
        raise VerifyFailure(f"{label} does not report two stable guarded passes")
    if record.get("payload_read") is not payload:
        raise VerifyFailure(f"{label} payload read scope differs")
    before_sha = _sha(record.get("sha256_pre"), f"{label} pre SHA")
    after_sha = _sha(record.get("sha256_post"), f"{label} post SHA")
    if before_sha != after_sha or record.get("post_equal") is not True:
        raise VerifyFailure(f"{label} pre/post SHA is not equal")
    declared = manifest_record.get("sha256")
    if isinstance(declared, str) and re.fullmatch(r"[0-9a-fA-F]{64}", declared) and before_sha != declared.lower():
        raise VerifyFailure(f"{label} SHA differs from manifest")
    _current_stat(observed_path, post, label)


def _manifest_cases(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_FOR_PARENT_GUARDED_OWNER_GRID_INITIAL_SUPPORT":
        raise VerifyFailure("manifest schema/status mismatch")
    rows = manifest.get("cases")
    if not isinstance(rows, list) or len(rows) != len(ROW_KEYS):
        raise VerifyFailure("manifest does not contain nine rows")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("sentinel_id") not in TARGETS or row.get("grid_label") not in GRIDS:
            raise VerifyFailure("manifest row identity is invalid")
        key = f"{row['sentinel_id']}:{row['grid_label']}"
        if key in result:
            raise VerifyFailure(f"duplicate manifest row {key}")
        result[key] = row
        owner = row.get("owner_predicate")
        if not isinstance(owner, dict) or owner.get("mass_rescale") is not False:
            raise VerifyFailure(f"{key} owner/mass policy is unsafe")
    if set(result) != set(ROW_KEYS):
        raise VerifyFailure("manifest row set is incomplete")
    scope = manifest.get("scientific_scope")
    if not isinstance(scope, dict) or scope.get("neighbor_grid_truth") is not False or scope.get("scientific_credit") != 0:
        raise VerifyFailure("manifest advertises unsupported scientific credit")
    return result


def _verify_row(row: dict[str, Any], case: dict[str, Any], key: str) -> None:
    status = str(row.get("status", ""))
    if status.startswith("FAILED"):
        if row.get("admission", {}).get("scientific_credit", 0) != 0:
            raise VerifyFailure(f"{key} failed row advertises credit")
        return
    if status != "PASS_INITIAL_SUPPORT_DIAGNOSTIC":
        raise VerifyFailure(f"{key} has unknown row status {status!r}")
    admission = row.get("admission")
    if not isinstance(admission, dict) or any(admission.get(name) != UNKNOWN for name in ("QI", "QN", "QE")) or admission.get("scientific_credit") != 0:
        raise VerifyFailure(f"{key} admission is not diagnostic-only")
    source_identity = row.get("source_identity")
    if not isinstance(source_identity, dict):
        raise VerifyFailure(f"{key} source identity is missing")
    for name in ("source_xml", "source_def", "candidate_def", "gencase_receipt"):
        if not isinstance(source_identity.get(name), dict):
            raise VerifyFailure(f"{key} source identity lacks {name}")
    xml = row.get("generated_xml")
    if not isinstance(xml, dict) or not isinstance(xml.get("guard"), dict):
        raise VerifyFailure(f"{key} generated XML guard is missing")
    # generated.xml is a bounded metadata input and is intentionally parsed
    # by the worker; the verifier itself still only checks the resulting
    # guard/stat record and does not reopen it.
    _guard(xml["guard"], case["generated_xml"], f"{key} generated XML", payload=True)
    payloads = row.get("deferred_payload_guards")
    if not isinstance(payloads, dict):
        raise VerifyFailure(f"{key} deferred payload guards are missing")
    _guard(payloads.get("fluid_vtk"), case["fluid_vtk"], f"{key} Fluid VTK", payload=True)
    _guard(payloads.get("bound_vtk"), case["bound_vtk"], f"{key} Bound VTK", payload=True)
    _guard(payloads.get("native_bi4"), case["native_bi4"], f"{key} native BI4", payload=True)
    fluid = row.get("fluid"); bound = row.get("bound")
    if not isinstance(fluid, dict) or fluid.get("finite_points") is not True:
        raise VerifyFailure(f"{key} fluid finite diagnostic is missing")
    if not isinstance(bound, dict) or bound.get("finite_points") is not True:
        raise VerifyFailure(f"{key} bound finite diagnostic is missing")
    generated_meta = xml.get("metadata")
    if not isinstance(generated_meta, dict):
        raise VerifyFailure(f"{key} generated XML metadata is missing")
    if fluid.get("xml_fluid_count") != generated_meta.get("fluid_count"):
        raise VerifyFailure(f"{key} XML/fluid count join is incomplete")
    header = row.get("native_header")
    if not isinstance(header, dict):
        raise VerifyFailure(f"{key} native header status is missing")
    if header.get("status") == "PASS_NATIVE_HEADER_FIELDS":
        _sha(header.get("source_sha256"), f"{key} native header source SHA")
        native_sha = payloads["native_bi4"].get("sha256_post")
        if header["source_sha256"] != native_sha:
            raise VerifyFailure(f"{key} native header is not joined to native BI4 SHA")
        if header.get("xml_mass_is_not_native") is not True or header.get("native_header_values_only") is not True:
            raise VerifyFailure(f"{key} native header mass semantics are unsafe")
        if header.get("massfluid") == "UNKNOWN" or header.get("massbound") == "UNKNOWN":
            raise VerifyFailure(f"{key} native header PASS omits MassFluid/MassBound fields")
    elif not str(header.get("status", "")).startswith("UNKNOWN"):
        raise VerifyFailure(f"{key} native header has unsupported status")
    owner = row.get("source_geometry_contract", {}).get("owner_predicate")
    if not isinstance(owner, dict) or owner.get("mass_rescale") is not False:
        raise VerifyFailure(f"{key} output owner predicate is unsafe")


def verify(manifest_path: Path, output_path: Path, verification_output: Path | None = None) -> dict[str, Any]:
    manifest, manifest_record = _read_json(manifest_path, "owner-grid support manifest")
    cases = _manifest_cases(manifest)
    output, output_record = _read_json(output_path, "owner-grid support report")
    if output.get("schema") != WORKER_SCHEMA or not str(output.get("status", "")).startswith("COMPLETE_"):
        raise VerifyFailure("worker report schema/status mismatch")
    rows = output.get("cases")
    if not isinstance(rows, list) or len(rows) != len(ROW_KEYS):
        raise VerifyFailure("worker report does not contain nine rows")
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("row_key"), str):
            raise VerifyFailure("worker report row identity is malformed")
        if row["row_key"] in by_key:
            raise VerifyFailure(f"duplicate worker report row {row['row_key']}")
        by_key[row["row_key"]] = row
    if set(by_key) != set(ROW_KEYS):
        raise VerifyFailure("worker report row set differs from manifest")
    for key in ROW_KEYS:
        _verify_row(by_key[key], cases[key], key)
    calculated = {
        "PASS_OR_DIAGNOSTIC": sum(not str(by_key[key].get("status", "")).startswith("FAILED") for key in ROW_KEYS),
        "FAILED": sum(str(by_key[key].get("status", "")).startswith("FAILED") for key in ROW_KEYS),
    }
    declared_counts = output.get("case_counts")
    if declared_counts != calculated:
        raise VerifyFailure(f"worker case_counts do not match row statuses: {declared_counts!r} != {calculated!r}")
    scope = output.get("scientific_scope")
    if not isinstance(scope, dict) or scope.get("scientific_credit") != 0 or scope.get("neighbor_grid_truth") is not False:
        raise VerifyFailure("worker report scientific scope is unsafe")
    result = {"schema": SCHEMA, "status": "VERIFIED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_V1",
              "manifest": manifest_record, "worker_output": output_record,
              "case_counts": output.get("case_counts"), "scientific_qualification": QUALIFICATION,
              "read_scope": {"vtk_bytes_read_by_verifier": False, "bi4_bytes_read_by_verifier": False,
                             "hdf5_read": False, "solver_launch": False, "gencase_launch": False}}
    if verification_output is not None:
        path = _absolute(verification_output)
        if path.exists() or path.is_symlink():
            raise VerifyFailure(f"refusing overwrite: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def self_test() -> None:
    spec = importlib.util.spec_from_file_location("owner_grid_support_worker_for_verify", WORKER_PATH)
    if spec is None or spec.loader is None:
        raise VerifyFailure("cannot load worker for fixture")
    worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
    with tempfile.TemporaryDirectory(prefix="owner-grid-verify-") as value:
        root = Path(value); manifest_path = worker._fixture_manifest(root); output = root / "report.json"
        worker.run(manifest_path, root / "attempt", output)
        result = verify(manifest_path, output)
        assert result["case_counts"] == {"PASS_OR_DIAGNOSTIC": 9, "FAILED": 0}
        tampered = json.loads(output.read_text(encoding="utf-8"))
        tampered["cases"][0]["native_header"]["status"] = "PASS_NATIVE_HEADER_FIELDS"
        tampered["cases"][0]["native_header"].pop("source_sha256", None)
        broken = root / "broken.json"; broken.write_text(json.dumps(tampered), encoding="utf-8")
        try:
            verify(manifest_path, broken)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("native header without source SHA was accepted")
        tampered = json.loads(output.read_text(encoding="utf-8"))
        tampered["cases"][0]["source_geometry_contract"]["owner_predicate"]["mass_rescale"] = True
        broken2 = root / "broken-owner.json"; broken2.write_text(json.dumps(tampered), encoding="utf-8")
        try:
            verify(manifest_path, broken2)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("owner mass-rescale promotion was accepted")
    print("PASS_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_VERIFIER_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--manifest", type=Path); parser.add_argument("--output", type=Path)
    parser.add_argument("--verification-output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            self_test()
        except Exception as exc:
            print(f"FAILED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_VERIFIER_SELFTEST: {exc}", file=sys.stderr); return 2
        return 0
    if args.manifest is None or args.output is None:
        parser.error("--verify requires --manifest and --output")
    try:
        result = verify(args.manifest, args.output, args.verification_output)
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_INITIAL_SUPPORT_VERIFIER: {exc}", file=sys.stderr); return 2
    print(json.dumps({"status": result["status"], "case_counts": result["case_counts"], "scientific_credit": 0}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
