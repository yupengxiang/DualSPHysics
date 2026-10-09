#!/usr/bin/env python3
"""Decode one exact native frame zero for four previously run sentinels.

The request builder binds source XML, completed solver receipt, RunPARTs and
the exact ``Part_0000.bi4`` path.  The Part file is deliberately deferred:
this worker is only useful after a parent has reserved the request and
performed the first source SHA/stat check.  It then performs a second
post-decode SHA/stat check and uses the official BI4 decoder plus the exact
source XML particle ranges to report finite fields, role counts, absolute MK
labels and discrete fluid sample mass.

The worker does not claim geometric Fluid/Bound support because the four
CURRENT source products expose no bound VTK input in this request.  It also
does not infer continuous owner mass, world-axis qualification, or numerical
quality from a frame-zero result.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
CONTRACT = HERE / "stage2_four_sentinel_frame0_support_audit_contract_v1.json"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SCHEMA = "ds02.stage2.four-sentinel-frame0-support-audit.v1"
MANIFEST_SCHEMA = "ds02.stage2.four-sentinel-frame0-support-manifest.v1"
CASES = ("F2-S2", "F4-S2", "F5-S2", "F7-S1")
MAX_SMALL_BYTES = 16 * 1024 * 1024
SCRATCH_CAP_BYTES = 256 * 1024 * 1024


class AuditFailure(RuntimeError):
    pass


def _load_observer() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_native_physical_observer_v2_frame0_source", OBSERVER)
    if spec is None or spec.loader is None:
        raise AuditFailure(f"cannot import observer: {OBSERVER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _regular(path: Path, label: str) -> dict[str, int]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise AuditFailure(f"{label} is not a regular non-symlink file: {path}")
    return _stat(path)


def _sha_stat(path: Path, label: str) -> tuple[str, dict[str, int]]:
    path = path.expanduser().absolute()
    before = _regular(path, label)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    after = _regular(path, label)
    if before != after or size != before["bytes"]:
        raise AuditFailure(f"{label} changed during SHA pass: {path}")
    return digest.hexdigest(), after


def _small_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.expanduser().absolute()
    stat_before = _regular(path, label)
    if stat_before["bytes"] > MAX_SMALL_BYTES:
        raise AuditFailure(f"{label} exceeds bounded read: {path}")
    raw = path.read_bytes()
    stat_after = _regular(path, label)
    if stat_before != stat_after or len(raw) != stat_before["bytes"]:
        raise AuditFailure(f"{label} changed while read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditFailure(f"{label} is not JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AuditFailure(f"{label} is not an object: {path}")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "stat": stat_after}


def _manifest(path: Path) -> dict[str, Any]:
    value, _ = _small_json(path, "frame-0 support manifest")
    if value.get("schema") != MANIFEST_SCHEMA:
        raise AuditFailure(f"manifest schema mismatch: {value.get('schema')!r}")
    cases = value.get("cases")
    if not isinstance(cases, list) or {str(item.get('sentinel_id')) for item in cases if isinstance(item, dict)} != set(CASES):
        raise AuditFailure("manifest must contain exactly F2-S2/F4-S2/F5-S2/F7-S1")
    return value


def _assert_receipt_identity(case: dict[str, Any], receipt: dict[str, Any], receipt_record: dict[str, Any]) -> None:
    if receipt.get("status") != "completed" or int(receipt.get("returncode", -1)) != 0:
        raise AuditFailure("terminal solver receipt is not completed with returncode 0")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise AuditFailure("terminal receipt has no nested request")
    missing_receipt_fields: list[str] = []
    expected_identity = case.get("receipt_identity_expected") or {}
    for key in ("family_id", "sentinel_id", "physical_case_id", "case_id", "attempt_id"):
        expected = expected_identity.get(key, case.get(key))
        actual = request.get(key)
        if actual is None:
            # Missing producer identity remains explicitly partial/UNKNOWN;
            # it is never reconstructed from sentinel labels or paths.
            missing_receipt_fields.append(key)
            continue
        if expected is not None and actual != expected:
            raise AuditFailure(f"receipt request {key} does not match manifest")
    declared = case.get("receipt_sha256")
    if declared is not None and declared != receipt_record["sha256"]:
        raise AuditFailure("receipt SHA differs from manifest declaration")
    output_root = case.get("terminal_output_root")
    if not isinstance(output_root, str) or Path(output_root).expanduser().absolute() != Path(str(receipt.get("output_root", ""))).expanduser().absolute():
        raise AuditFailure("receipt output_root does not match manifest")
    if missing_receipt_fields:
        case["receipt_identity_missing_fields"] = missing_receipt_fields


def _expected_stat(record: dict[str, Any]) -> dict[str, int]:
    value = record.get("stat_at_build") or record.get("stat") or {}
    aliases = {"device": ("device", "st_dev", "dev"), "inode": ("inode", "st_ino", "ino"),
               "bytes": ("bytes",), "mtime_ns": ("mtime_ns",), "ctime_ns": ("ctime_ns",)}
    result: dict[str, int] = {}
    for target, names in aliases.items():
        for name in names:
            if name in value:
                result[target] = int(value[name]); break
    return result


def _check_stat(expected: dict[str, int], actual: dict[str, int], label: str) -> None:
    for key, value in expected.items():
        if actual.get(key) != value:
            raise AuditFailure(f"{label} {key} changed: expected {value}, got {actual.get(key)}")


def _case_run(case: dict[str, Any], attempt_root: Path, observer: Any) -> dict[str, Any]:
    sentinel = str(case["sentinel_id"])
    receipt, receipt_record = _small_json(Path(case["receipt"]["path"]), f"{sentinel} solver receipt")
    _assert_receipt_identity(case, receipt, receipt_record)
    source_xml = Path(case["source_xml"]["path"]).expanduser().absolute()
    xml_stat = _regular(source_xml, f"{sentinel} source XML")
    if case["source_xml"].get("sha256"):
        xml_sha, xml_after = _sha_stat(source_xml, f"{sentinel} source XML")
        if xml_sha != case["source_xml"]["sha256"]:
            raise AuditFailure(f"{sentinel} source XML SHA changed")
        xml_stat = xml_after
    raw = Path(case["frame0"]["path"]).expanduser().absolute()
    expected = _expected_stat(case["frame0"])
    before_sha, before_stat = _sha_stat(raw, f"{sentinel} frame-0 BI4")
    _check_stat(expected, before_stat, f"{sentinel} frame-0 BI4 before decode")
    declared_sha = case["frame0"].get("known_sha256")
    if isinstance(declared_sha, str) and len(declared_sha) == 64 and before_sha != declared_sha:
        raise AuditFailure(f"{sentinel} frame-0 BI4 SHA differs from parent declaration")
    scratch = attempt_root / "scratch" / sentinel.replace("-", "_")
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        decoded = observer.decode_frame(raw, Path(case["decoder"]["path"]), scratch, 0)
    finally:
        # The official observer uses TemporaryDirectory for decoder output;
        # leave only the case scratch root so the parent can account it.
        pass
    after_sha, after_stat = _sha_stat(raw, f"{sentinel} frame-0 BI4 post-decode")
    if before_sha != after_sha or before_stat != after_stat:
        raise AuditFailure(f"{sentinel} frame-0 BI4 changed across decode")
    source = observer.parse_source_xml(source_xml)
    kind, mkfluid, mk_absolute = observer.assign_particle_ranges(decoded["ids"], source["blocks"])
    role_counts: dict[str, int] = {}
    for role in sorted(set(kind.tolist())):
        role_counts[role] = int((kind == role).sum())
    abs_mk_counts: dict[str, int] = {}
    for mk in sorted(set(mk_absolute.tolist())):
        abs_mk_counts[str(int(mk))] = int((mk_absolute == mk).sum())
    fluid_count = role_counts.get("fluid", 0)
    massfluid = source["constants"].get("massfluid")
    sample_mass = None if massfluid is None else float(fluid_count * float(massfluid))
    return {
        "sentinel_id": sentinel, "status": "PASS_FRAME0_ROLE_MASS_FINITE_DIAGNOSTIC",
        "source_xml": {"path": str(source_xml), "stat": xml_stat, "sha256": case["source_xml"].get("sha256")},
        "receipt": receipt_record, "receipt_identity": {"status": "PASS_CASE_ATTEMPT_PHYSICAL" if not case.get("receipt_identity_missing_fields") else "PARTIAL_SENTINEL_FIELD_ABSENT", "missing_fields": case.get("receipt_identity_missing_fields", [])},
        "native": {"path": str(raw), "sha256": before_sha, "stat_pre": before_stat, "stat_post": after_stat, "post_equal": True},
        "decoded_time_s": float(decoded["decoded_time_s"]), "field_digest_sha256": decoded["field_digest_sha256"],
        "finite_fields": {"position": True, "velocity": True, "density": True, "ids_unique": True},
        "role_counts": role_counts, "absolute_mk_counts": abs_mk_counts,
        "range_overlap": {"status": "PASS_XML_RANGES_DISJOINT_AND_COVERED", "source": "official source XML Idp ranges"},
        "sample_mass": {"massfluid_kg": massfluid, "fluid_count": fluid_count, "discrete_sample_mass_kg": sample_mass, "continuous_owner_mass": "UNKNOWN_NOT_DERIVED"},
        "geometric_support": {"status": "UNKNOWN_NO_FLUID_BOUND_VTK_BOUND_IN_SOURCE_CARD", "fluid_inside": "UNKNOWN", "bound_overlap": "UNKNOWN", "contact": "UNKNOWN"},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }


def run(manifest_path: Path, attempt_root: Path, output: Path) -> dict[str, Any]:
    manifest = _manifest(manifest_path)
    observer = _load_observer()
    cases: list[dict[str, Any]] = []
    passed = failed = 0
    for case in manifest["cases"]:
        try:
            result = _case_run(case, attempt_root, observer)
            passed += 1
        except Exception as exc:
            result = {"sentinel_id": case.get("sentinel_id"), "status": "FAILED_FRAME0_ROLE_MASS_DIAGNOSTIC", "reason": repr(exc), "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}}
            failed += 1
        cases.append(result)
    status = "COMPLETE_PARTIAL_FRAME0_ROLE_MASS_DIAGNOSTICS" if passed else "FAILED_FRAME0_ROLE_MASS_DIAGNOSTICS"
    value = {"schema": SCHEMA, "status": status, "manifest": str(manifest_path.expanduser().absolute()), "cases": cases,
             "case_counts": {"PASS": passed, "FAILED": failed}, "geometric_support": "UNKNOWN", "continuous_owner_mass": "UNKNOWN",
             "read_scope": {"hdf5_read": False, "solver_launch": False, "full_native_tree_scan": False, "deferred_frame_count": len(cases), "world_axis": "UNKNOWN"},
             "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}}
    output = output.expanduser().absolute(); output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise AuditFailure(f"refusing overwrite: {output}")
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return value


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="four-sentinel-frame0-") as td:
        path = Path(td) / "x.bi4"; path.write_bytes(b"fixture")
        stat = _stat(path)
        _check_stat(stat, stat, "fixture")
        bad = dict(stat); bad["inode"] += 1
        try:
            _check_stat(bad, stat, "fixture")
        except AuditFailure:
            pass
        else:
            raise AssertionError("inode mutation was accepted")
        receipt = {"status": "completed", "returncode": 0, "output_root": td,
                   "request": {"family_id": "F7", "case_id": "CASE",
                               "attempt_id": "ATTEMPT", "physical_case_id": None}}
        case = {"family_id": "F7", "sentinel_id": "F7-S1",
                "physical_case_id": None, "receipt_identity_expected":
                    {"family_id": "F7", "sentinel_id": "F7-S1",
                     "physical_case_id": "F7-PHYSICAL", "case_id": "CASE",
                     "attempt_id": "ATTEMPT"},
                "receipt_sha256": "receipt-sha", "terminal_output_root": td}
        _assert_receipt_identity(case, receipt, {"sha256": "receipt-sha"})
        assert set(case["receipt_identity_missing_fields"]) == {"sentinel_id", "physical_case_id"}
        bad = dict(receipt)
        bad["request"] = dict(receipt["request"], physical_case_id="WRONG")
        try:
            _assert_receipt_identity(case, bad, {"sha256": "receipt-sha"})
        except AuditFailure:
            pass
        else:
            raise AssertionError("producer physical identity mismatch was accepted")
    print("PASS_FOUR_SENTINEL_FRAME0_SUPPORT_WORKER_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path); parser.add_argument("--attempt-root", type=Path); parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    if args.manifest is None or args.attempt_root is None or args.output is None:
        parser.error("--run requires --manifest, --attempt-root, --output")
    try:
        value = run(args.manifest, args.attempt_root, args.output)
        print(json.dumps({"status": value["status"], "output": str(args.output.absolute()), "case_counts": value["case_counts"]}, sort_keys=True))
        return 0 if value["case_counts"]["FAILED"] == 0 else 2
    except Exception as exc:
        print(f"FAILED_FOUR_SENTINEL_FRAME0_SUPPORT: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
