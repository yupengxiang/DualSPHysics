#!/usr/bin/env python3
"""Verify a ROOT316 geometry-support worker result without rereading payloads.

The producer worker is responsible for the guarded VTK reads.  This additive
verifier checks that its report is consistent with the manifest and request,
that all eight VTK and four BI4 bindings are present, and that the current
stat-only bindings have not changed.  It deliberately does not open VTK,
BI4, HDF5, or solver payloads.  Its result grants no scientific qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
SCHEMA = "ds02.stage2.four-sentinel-gencase-geometry-support-output-verifier.v1"
WORKER_SCHEMA = "ds02.stage2.four-sentinel-gencase-geometry-support-audit.v1"
MANIFEST_SCHEMA = "ds02.stage2.four-sentinel-gencase-geometry-support-manifest.v1"
REQUEST_SCHEMA = "ds02.request.v1"
CASES = ("F2-S2", "F4-S2", "F5-S2", "F7-S1")
MAX_SMALL_BYTES = 32 * 1024 * 1024


class VerifyFailure(RuntimeError):
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


def _regular(path: Path, label: str) -> Path:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise VerifyFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise VerifyFailure(f"{label} exceeds verifier JSON cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise VerifyFailure(f"{label} changed during verifier read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise VerifyFailure(f"{label} must be an object")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "stat": after}


def _expected_stat(record: dict[str, Any]) -> dict[str, int]:
    source = record.get("stat") or record.get("stat_at_build") or {}
    if not source and all(key in record for key in ("device", "inode", "bytes", "mtime_ns", "ctime_ns")):
        source = record
    aliases = {
        "device": ("device", "dev", "st_dev"),
        "inode": ("inode", "ino", "st_ino"),
        "bytes": ("bytes",),
        "mtime_ns": ("mtime_ns",),
        "ctime_ns": ("ctime_ns",),
    }
    result: dict[str, int] = {}
    for target, names in aliases.items():
        for name in names:
            if name in source:
                result[target] = int(source[name])
                break
    return result


def _assert_stat(path: Path, record: dict[str, Any], label: str) -> dict[str, int]:
    actual = _stat(_regular(path, label))
    expected = _expected_stat(record)
    missing = set(("device", "inode", "bytes", "mtime_ns", "ctime_ns")) - set(expected)
    if missing:
        raise VerifyFailure(f"{label} lacks expected stat fields: {sorted(missing)}")
    if actual != expected:
        raise VerifyFailure(f"{label} stat changed: expected {expected}, got {actual}")
    return actual


def _case_map(value: dict[str, Any], key: str = "cases") -> dict[str, dict[str, Any]]:
    rows = value.get(key)
    if not isinstance(rows, list):
        raise VerifyFailure(f"{key} must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("sentinel_id"), str):
            raise VerifyFailure(f"{key} contains a malformed case")
        sid = row["sentinel_id"]
        if sid in result:
            raise VerifyFailure(f"duplicate case {sid}")
        result[sid] = row
    if set(result) != set(CASES):
        raise VerifyFailure(f"expected exactly {CASES}, got {sorted(result)}")
    return result


def _deferred_map(manifest: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    cases = _case_map(manifest)
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for sid, case in cases.items():
        for kind in ("fluid_vtk", "bound_vtk", "generated_bi4"):
            record = case.get(kind)
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise VerifyFailure(f"{sid} missing {kind} deferred record")
            if "sha256" in record and record.get("sha256") not in (None, ""):
                raise VerifyFailure(f"{sid} {kind} has an unguarded manifest SHA")
            result[(sid, kind)] = record
    if len(result) != 12:
        raise VerifyFailure(f"expected 12 deferred payload records, got {len(result)}")
    return result


def _verify_manifest(manifest: dict[str, Any], manifest_record: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise VerifyFailure(f"manifest schema mismatch: {manifest.get('schema')!r}")
    if manifest.get("status") != "READY_FOR_PARENT_GUARDED_VTK_SUPPORT":
        raise VerifyFailure("manifest is not a ROOT316 guarded-support manifest")
    deferred = _deferred_map(manifest)
    for sid, case in _case_map(manifest).items():
        owner = case.get("continuous_owner")
        if not isinstance(owner, dict):
            raise VerifyFailure(f"{sid} lacks continuous-owner policy")
        if sid == "F2-S2":
            if owner.get("status") != "UNVERIFIED_CROSS_SENTINEL_TARGET" or owner.get("target_source_sentinel") != "F2-S1":
                raise VerifyFailure("F2-S2 owner policy is not the unverified cross-sentinel target")
            if owner.get("target_mass_kg") != 18.876 or owner.get("mass_rescale") is not False:
                raise VerifyFailure("F2-S2 owner target policy changed")
        else:
            if owner.get("status") != "UNKNOWN_CONTINUOUS_OWNER" or owner.get("target_mass_kg") is not None:
                raise VerifyFailure(f"{sid} has an unsupported owner target")
        geometry = case.get("source_geometry_metadata")
        if isinstance(geometry, dict) and geometry.get("fluid_particle_count") is not None:
            if not isinstance(geometry.get("fluid_particle_count"), int) or geometry["fluid_particle_count"] < 0:
                raise VerifyFailure(f"{sid} has an invalid XML fluid count")
    scope = manifest.get("scientific_scope")
    if not isinstance(scope, dict) or scope.get("mass_rescale") is not False or scope.get("neighbor_grid_truth") is not False:
        raise VerifyFailure("manifest scientific scope permits an unsupported shortcut")
    if manifest_record.get("sha256") is None:
        raise VerifyFailure("manifest record has no source SHA")
    return deferred


def _verify_request(request: dict[str, Any], manifest: dict[str, Any], manifest_path: Path, manifest_record: dict[str, Any], deferred: dict[tuple[str, str], dict[str, Any]]) -> None:
    if request.get("schema") != REQUEST_SCHEMA or request.get("variant_schema") != WORKER_SCHEMA:
        raise VerifyFailure("request schema/variant mismatch")
    if request.get("status") != "READY_FOR_PARENT_GUARDED_VTK_SUPPORT" or request.get("parent_wrapper_required") is not True:
        raise VerifyFailure("request does not require the parent deferred-payload wrapper")
    if request.get("parent_v8_deferred_fields_not_credit") is not True:
        raise VerifyFailure("request does not disclose v8 deferred-field limits")
    command = request.get("command")
    if not isinstance(command, list) or "--run" not in command or "--manifest" not in command:
        raise VerifyFailure("request command is not an executable worker command")
    if not any(Path(str(item)).name == manifest_path.name for item in command):
        raise VerifyFailure("request command does not bind the supplied manifest")
    request_records = request.get("input_records")
    input_sha = request.get("input_sha256")
    input_files = request.get("input_files")
    if not isinstance(request_records, dict) or not isinstance(input_sha, dict) or not isinstance(input_files, list):
        raise VerifyFailure("request input contract is incomplete")
    if set(input_files) != set(request_records):
        raise VerifyFailure("request input_files and input_records differ")
    manifest_input = request_records.get(str(_absolute(manifest_path)))
    if not isinstance(manifest_input, dict) or manifest_input.get("sha256") != manifest_record.get("sha256"):
        raise VerifyFailure("request does not bind the exact supplied manifest SHA")
    for path, record in request_records.items():
        if not isinstance(record, dict) or record.get("path") != path:
            raise VerifyFailure(f"request input record path mismatch: {path}")
        if isinstance(record.get("sha256"), str) and input_sha.get(path) != record["sha256"]:
            raise VerifyFailure(f"request input SHA mismatch: {path}")
    deferred_rows = request.get("deferred_input_records")
    if not isinstance(deferred_rows, list) or len(deferred_rows) != 12:
        raise VerifyFailure("request must expose exactly 12 deferred payload records")
    observed: set[tuple[str, str]] = set()
    for record in deferred_rows:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise VerifyFailure("malformed deferred payload record")
        path = record["path"]
        matches = [(key, expected) for key, expected in deferred.items() if expected.get("path") == path]
        if len(matches) != 1:
            raise VerifyFailure(f"deferred record is not bound to the manifest: {path}")
        key, expected = matches[0]
        if key in observed:
            raise VerifyFailure(f"duplicate deferred record: {key}")
        observed.add(key)
        if _expected_stat(record) != _expected_stat(expected):
            raise VerifyFailure(f"deferred stat mismatch for {key}")
        if path in input_files:
            raise VerifyFailure(f"payload was incorrectly promoted to parent input_files: {path}")
    if observed != set(deferred):
        raise VerifyFailure("request deferred records do not cover all eight VTK/four BI4 bindings")
    request_cases = _case_map(request)
    manifest_cases = _case_map(manifest)
    for sid in CASES:
        if request_cases[sid].get("continuous_owner") != manifest_cases[sid].get("continuous_owner"):
            raise VerifyFailure(f"request/manifest owner policy differs for {sid}")


def _verify_guard_record(record: Any, expected: dict[str, Any], label: str, *, payload: bool) -> None:
    if not isinstance(record, dict) or record.get("path") != expected.get("path"):
        raise VerifyFailure(f"{label} path differs from manifest")
    if _expected_stat(record.get("stat_pre") if isinstance(record.get("stat_pre"), dict) else {}) != _expected_stat(expected):
        raise VerifyFailure(f"{label} pre-stat differs from manifest")
    if _expected_stat(record.get("stat_post") if isinstance(record.get("stat_post"), dict) else {}) != _expected_stat(expected):
        raise VerifyFailure(f"{label} post-stat differs from manifest")
    _assert_stat(Path(str(expected["path"])), expected, f"{label} current source")
    if payload:
        if record.get("payload_read") is not True or record.get("stable") is not True:
            raise VerifyFailure(f"{label} is not marked as a stable payload read")
        if record.get("complete_payload_passes") != 2:
            raise VerifyFailure(f"{label} does not report two guarded payload passes")
        sha_pre = record.get("sha256_pre"); sha_post = record.get("sha256_post")
        if not isinstance(sha_pre, str) or len(sha_pre) != 64 or sha_pre != sha_post:
            raise VerifyFailure(f"{label} has no equal full pre/post SHA")
    else:
        if record.get("payload_read") is not False:
            raise VerifyFailure(f"{label} was opened despite BI4 stat-only policy")
        if "sha256_pre" in record or "sha256_post" in record:
            raise VerifyFailure(f"{label} exposes an invalid payload SHA")


def _verify_output(output: dict[str, Any], manifest: dict[str, Any], deferred: dict[tuple[str, str], dict[str, Any]]) -> None:
    if output.get("schema") != WORKER_SCHEMA or output.get("status") != "COMPLETED_FLUID_BOUND_VTK_SUPPORT_DIAGNOSTIC":
        raise VerifyFailure("worker output schema/status mismatch")
    aggregate = output.get("aggregate")
    if not isinstance(aggregate, dict) or aggregate.get("QI") != "UNKNOWN" or aggregate.get("QN") != "UNKNOWN" or aggregate.get("QE") != "UNKNOWN":
        raise VerifyFailure("worker output grants unsupported scientific credit")
    if aggregate.get("continuous_owner_closed") is not False or aggregate.get("support_overlap_scientific_credit") is not False:
        raise VerifyFailure("worker output advertises owner/support credit")
    output_cases = _case_map(output)
    manifest_cases = _case_map(manifest)
    for sid in CASES:
        result = output_cases[sid]
        if result.get("continuous_owner") != manifest_cases[sid].get("continuous_owner"):
            raise VerifyFailure(f"{sid} output owner policy differs from manifest")
        admission = result.get("admission")
        if not isinstance(admission, dict) or any(admission.get("scientific_qualification", {}).get(key) != "UNKNOWN" for key in ("QI", "QN", "QE")):
            raise VerifyFailure(f"{sid} output scientific qualification is not UNKNOWN")
        source_xml = result.get("source_xml")
        if not isinstance(source_xml, dict) or not isinstance(source_xml.get("guard"), dict):
            raise VerifyFailure(f"{sid} output lacks generated XML guard")
        xml_expected = manifest_cases[sid].get("generated_xml")
        if source_xml["guard"].get("path") != xml_expected.get("path") or source_xml["guard"].get("sha256") != xml_expected.get("sha256"):
            raise VerifyFailure(f"{sid} XML guard does not join manifest")
        source_identity = result.get("source_identity")
        if not isinstance(source_identity, dict):
            raise VerifyFailure(f"{sid} output lacks source identity")
        for key, manifest_key in (("gencase_receipt", "gencase_receipt"), ("solver_receipt", "current_solver_receipt")):
            guard = source_identity.get(key); expected = manifest_cases[sid].get(manifest_key)
            if not isinstance(guard, dict) or guard.get("path") != expected.get("path") or guard.get("sha256") != expected.get("sha256"):
                raise VerifyFailure(f"{sid} {key} does not join manifest")
        payload_guards = result.get("deferred_payload_guards")
        if not isinstance(payload_guards, dict):
            raise VerifyFailure(f"{sid} lacks deferred payload guards")
        _verify_guard_record(payload_guards.get("fluid_vtk"), deferred[(sid, "fluid_vtk")], f"{sid} Fluid VTK", payload=True)
        _verify_guard_record(payload_guards.get("bound_vtk"), deferred[(sid, "bound_vtk")], f"{sid} Bound VTK", payload=True)
        _verify_guard_record(payload_guards.get("bi4"), deferred[(sid, "generated_bi4")], f"{sid} BI4", payload=False)
        fluid = result.get("fluid")
        expected_count = (manifest_cases[sid].get("source_geometry_metadata") or {}).get("fluid_particle_count")
        if not isinstance(fluid, dict) or fluid.get("finite_points") is not True:
            raise VerifyFailure(f"{sid} fluid finite-point result is missing")
        if expected_count is not None and (fluid.get("point_count") != expected_count or fluid.get("xml_fluid_count") != expected_count):
            raise VerifyFailure(f"{sid} fluid/XML particle count mismatch")
        bound = result.get("bound")
        if not isinstance(bound, dict) or bound.get("finite_points") is not True:
            raise VerifyFailure(f"{sid} bound finite-point result is missing")
    scope = output.get("scope")
    if not isinstance(scope, dict) or scope.get("native_bi4_read") is not False or scope.get("hdf5_read") is not False or scope.get("solver_launch") is not False:
        raise VerifyFailure("worker output read scope is unsafe")


def verify(manifest_path: Path, request_path: Path, output_path: Path, verification_output: Path | None = None) -> dict[str, Any]:
    manifest, manifest_record = _read_json(manifest_path, "support manifest")
    request, _ = _read_json(request_path, "support request")
    output, output_record = _read_json(output_path, "support worker output")
    deferred = _verify_manifest(manifest, manifest_record)
    _verify_request(request, manifest, _absolute(manifest_path), manifest_record, deferred)
    _verify_output(output, manifest, deferred)
    result = {
        "schema": SCHEMA,
        "status": "VERIFIED_SUPPORT_WORKER_CONTRACT_ONLY",
        "manifest": manifest_record,
        "request": {"path": str(_absolute(request_path)), "sha256": _read_json(request_path, "support request")[1]["sha256"]},
        "worker_output": output_record,
        "cases": list(CASES),
        "payload_bindings": {"vtk": 8, "bi4_stat_only": 4, "production_payload_reopened_by_verifier": False},
        "owner_status": {"F2-S2": "UNVERIFIED_CROSS_SENTINEL_TARGET", "F4-S2": "UNKNOWN_CONTINUOUS_OWNER", "F5-S2": "UNKNOWN_CONTINUOUS_OWNER", "F7-S1": "UNKNOWN_CONTINUOUS_OWNER"},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "scope": {"vtk_bytes_read": False, "bi4_bytes_read": False, "hdf5_read": False, "solver_launch": False},
    }
    if verification_output is not None:
        path = _absolute(verification_output)
        if path.exists() or path.is_symlink():
            raise VerifyFailure(f"refusing overwrite: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    return result


def _load_worker(path: Path):
    spec = importlib.util.spec_from_file_location("root316_support_worker_fixture", path)
    if spec is None or spec.loader is None:
        raise VerifyFailure(f"cannot load worker fixture: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_request(root: Path, worker: Any) -> tuple[Path, Path, Path]:
    xml = root / "case.xml"
    xml.write_text("""<case><casedef><definition dp=\"0.1\"/><mainlist><setmkfluid mk=\"1\"/><drawbox><point x=\"0\" y=\"0\" z=\"0\"/><size x=\"1\" y=\"1\" z=\"1\"/></drawbox><setmkbound mk=\"2\"/></mainlist></casedef><execution><particles><fluid begin=\"0\" count=\"2\" mkfluid=\"0\" mk=\"1\"/><bound begin=\"2\" count=\"1\" mkbound=\"2\" mk=\"2\"/></particles><constants><massfluid value=\"0.5\"/></constants></execution></case>""", encoding="utf-8")
    fluid_bytes = worker._tiny_vtk([(0.25, 0.25, 0.25), (0.75, 0.75, 0.75)], [0, 1])
    bound_bytes = worker._tiny_vtk([(0.25, 0.25, 0.25)], [2])
    receipt = root / "gencase-receipt.json"; solver = root / "solver-receipt.json"
    receipt.write_text('{"status":"completed","returncode":0}\n', encoding="utf-8")
    solver.write_text('{"status":"completed","returncode":0}\n', encoding="utf-8")
    def rec(path: Path, *, payload: bool) -> dict[str, Any]:
        value = _stat(path); result = {"path": str(path), "stat": value, "status": "PRESENT_STAT_ONLY"}
        if payload:
            result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result
    xml_rec = {"path": str(xml), "stat": _stat(xml), "sha256": hashlib.sha256(xml.read_bytes()).hexdigest()}
    cases = []
    for sid in CASES:
        fluid = root / f"{sid}_Fluid.vtk"; bound = root / f"{sid}_Bound.vtk"; bi4 = root / f"{sid}.bi4"
        fluid.write_bytes(fluid_bytes)
        bound.write_bytes(bound_bytes)
        bi4.write_bytes(b"tiny-bi4-not-opened")
        cases.append({
            "sentinel_id": sid, "family_id": sid.split("-")[0], "source_row_physical_case_id": "tiny-" + sid,
            "generated_xml": xml_rec, "gencase_receipt": rec(receipt, payload=True), "current_solver_receipt": rec(solver, payload=True),
            "fluid_vtk": rec(fluid, payload=False), "bound_vtk": rec(bound, payload=False), "generated_bi4": rec(bi4, payload=False),
            "source_geometry_metadata": {"fluid_particle_count": 2},
            "continuous_owner": ({"status": "UNVERIFIED_CROSS_SENTINEL_TARGET", "target_mass_kg": 18.876, "target_source_sentinel": "F2-S1", "mass_rescale": False} if sid == "F2-S2" else {"status": "UNKNOWN_CONTINUOUS_OWNER", "target_mass_kg": None, "mass_rescale": False}),
        })
    manifest = {"schema": "ds02.stage2.four-sentinel-gencase-geometry-support-manifest.v1", "status": "READY_FOR_PARENT_GUARDED_VTK_SUPPORT", "cases": cases, "scientific_scope": {"mass_rescale": False, "neighbor_grid_truth": False}}
    manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    def mrec(path: Path) -> dict[str, Any]:
        raw = path.read_bytes(); return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "stat": _stat(path)}
    manifest_record = mrec(manifest_path)
    deferred = [item for case in cases for item in (case["fluid_vtk"], case["bound_vtk"], case["generated_bi4"])]
    static_records = {manifest_record["path"]: manifest_record}
    request = {"schema": "ds02.request.v1", "variant_schema": "ds02.stage2.four-sentinel-gencase-geometry-support-audit.v1", "status": "READY_FOR_PARENT_GUARDED_VTK_SUPPORT", "parent_wrapper_required": True, "parent_v8_deferred_fields_not_credit": True, "command": ["/tmp/python", "worker.py", "--run", "--manifest", str(manifest_path)], "input_files": sorted(static_records), "input_records": static_records, "input_sha256": {manifest_record["path"]: manifest_record["sha256"]}, "deferred_input_records": deferred, "cases": cases}
    request_path = root / "request.json"; request_path.write_text(json.dumps(request), encoding="utf-8")
    output_path = root / "worker-output.json"
    worker.run_manifest(manifest, output_path, root / "attempt")
    return manifest_path, request_path, output_path


def self_test() -> None:
    worker_path = HERE / "stage2_four_sentinel_gencase_geometry_support_audit_v1.py"
    with tempfile.TemporaryDirectory(prefix="four-sentinel-support-verifier-") as td:
        root = Path(td)
        worker = _load_worker(worker_path)
        manifest_path, request_path, output_path = _fixture_request(root, worker)
        result = verify(manifest_path, request_path, output_path)
        assert result["status"] == "VERIFIED_SUPPORT_WORKER_CONTRACT_ONLY"
        assert result["payload_bindings"] == {"vtk": 8, "bi4_stat_only": 4, "production_payload_reopened_by_verifier": False}
        # An ASCII replacement is a real VTK-format mutation.  The verifier
        # rejects it from the stat contract before opening the replacement.
        fluid = root / "F2-S2_Fluid.vtk"
        original = fluid.read_bytes()
        fluid.write_text("# vtk DataFile Version 3.0\ntiny\nASCII\nDATASET POLYDATA\n", encoding="ascii")
        try:
            verify(manifest_path, request_path, output_path)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("ASCII VTK replacement was accepted")
        fluid.write_bytes(original)
        # A bad XML particle count is rejected from the output/manifest join.
        altered = json.loads(manifest_path.read_text())
        altered["cases"][0]["source_geometry_metadata"]["fluid_particle_count"] = 99
        bad_manifest = root / "bad-count-manifest.json"; bad_manifest.write_text(json.dumps(altered), encoding="utf-8")
        try:
            verify(bad_manifest, request_path, output_path)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("bad XML particle count was accepted")
        # A formerly unknown owner target must never be smuggled into another
        # sentinel by relabelling the output.
        altered_output = json.loads(output_path.read_text())
        altered_output["cases"][1]["continuous_owner"] = {"status": "KNOWN_OWNER_TARGET", "target_mass_kg": 1.0}
        bad_output = root / "bad-owner-output.json"; bad_output.write_text(json.dumps(altered_output), encoding="utf-8")
        try:
            verify(manifest_path, request_path, bad_output)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("unsupported owner target was accepted")
        # A deferred stat mutation is rejected without reading the payload.
        altered_manifest = json.loads(manifest_path.read_text())
        altered_manifest["cases"][0]["fluid_vtk"]["stat"]["bytes"] += 1
        bad_stat = root / "bad-stat-manifest.json"; bad_stat.write_text(json.dumps(altered_manifest), encoding="utf-8")
        try:
            verify(bad_stat, request_path, output_path)
        except VerifyFailure:
            pass
        else:
            raise AssertionError("deferred stat mutation was accepted")
    print("PASS_FOUR_SENTINEL_GENCASE_SUPPORT_VERIFIER_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verification-output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test(); return 0
    if args.manifest is None or args.request is None or args.output is None:
        parser.error("--verify requires --manifest, --request and --output")
    try:
        result = verify(args.manifest, args.request, args.output, args.verification_output)
    except (VerifyFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOUR_SENTINEL_SUPPORT_VERIFIER: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "cases": list(CASES), "vtk": 8, "bi4_stat_only": 4, "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
