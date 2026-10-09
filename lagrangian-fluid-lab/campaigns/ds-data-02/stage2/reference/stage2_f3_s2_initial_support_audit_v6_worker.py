#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""F3-S2 support audit V6 with a forward static-record comparison fix.

ROOT121 proved the V5 q/receipt join and source pre/post checks, then failed
after decoding because the consumed V3 worker compared complete record
dictionaries whose descriptive ``label`` values intentionally differed
between ``pre`` and ``post`` (``F3 key`` versus ``F3 key post``).  This
additive wrapper keeps the V3/V5 bytes unchanged and delegates through V5
while normalising only that descriptive field in the in-memory V3 record
function.  Identity fields (path, bytes, SHA, timestamps, device and inode)
remain part of the equality check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import importlib.util
import os
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V5_WORKER_PATH = HERE / "stage2_f3_s2_initial_support_audit_v5_worker.py"
SCHEMA = "ds02.stage2.f3.s2.initial-support-audit.v6"
REQUEST_SCHEMA = "ds02.request.v1"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
STATIC_EQUALITY_FIELDS = ("path", "bytes", "sha256", "mtime_ns", "ctime_ns", "st_dev", "st_ino")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V5 = load_module("stage2_f3_s2_initial_support_audit_v5_for_v6", V5_WORKER_PATH)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_record(record_function, path: Path, label: str, *, scope: str = "small_input_hashed_by_worker") -> dict[str, Any]:
    """Call the frozen recorder and remove only non-identity descriptions."""

    record = dict(record_function(path, label, scope=scope))
    record.pop("label", None)
    # A future recorder may add other explanatory fields.  Keep this forward
    # fix narrow: only the known descriptive label is excluded; all identity
    # fields are explicitly checked by the V3 equality comparison.
    return record


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    # V5 performs the strict q/receipt tuple check before calling V3.  Patch
    # only the in-memory recorder used by that delegated call, never its file.
    original_record = V5.V3.record

    def stable_record(path: Path, label: str, *, scope: str = "small_input_hashed_by_worker") -> dict[str, Any]:
        return _stable_record(original_record, path, label, scope=scope)

    V5.V3.record = stable_record
    try:
        report = V5.build_report(args)
    finally:
        V5.V3.record = original_record

    report = dict(report)
    report["schema"] = SCHEMA
    report["status"] = "COMPLETED_F3_S2_INITIAL_SUPPORT_AUDIT_V6"
    report["forward_worker"] = {
        "schema": SCHEMA,
        "delegated_worker_schema": "ds02.stage2.f3.s2.initial-support-audit.v5",
        "static_record_comparison": "identity_fields_only",
        "static_record_identity_fields": list(STATIC_EQUALITY_FIELDS),
        "static_record_descriptive_fields_excluded": ["label"],
        "q_receipt_join_before_dynamic_read": True,
        "solver_started": False,
    }
    report.setdefault("input_stability", {})["static_pre_post_identity_fields_only_equal"] = True
    report.setdefault("input_stability", {})["static_pre_post_descriptive_label_ignored"] = True
    return report


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable F3 v6 report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def _vtk_points(path: Path, *, with_idp: bool, begin: int = 1) -> None:
    points = struct.pack(">fff", 0.0, 0.0, 0.01)
    payload = b"# vtk DataFile Version 3.0\nfixture\nBINARY\nDATASET POLYDATA\nPOINTS 1 float\n" + points + b"\n"
    if with_idp:
        payload += b"POINT_DATA 1\nSCALARS Idp unsigned_int 1\nLOOKUP_TABLE default\n" + struct.pack(">I", begin) + b"\n"
    path.write_bytes(payload)


def _fixture_args(tmp: Path) -> argparse.Namespace:
    actual_root = tmp / "producer"
    actual_root.mkdir()
    q_path = tmp / "q.json"
    receipt_path = tmp / "receipt.json"
    generated_xml = actual_root / "generated.xml"
    fluid_vtk = actual_root / "generated_Fluid.vtk"
    bound_vtk = actual_root / "generated_Bound.vtk"
    source_xml = tmp / "source.xml"
    source_control = tmp / "control.csv"
    contract_path = tmp / "contract.json"
    output = tmp / "report.json"

    q = {
        "schema": REQUEST_SCHEMA,
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": "F3_FIXTURE_CASE",
        "attempt_id": "f3-fixture-attempt",
        "cpu_task_kind": "gencase",
        "gencase_launch": True,
        "solver_launch": False,
        "hdf5_read": False,
        "bi4_read": False,
        "source_binding": {"grid": "dp015", "dp_m": 0.015, "mode": "new_gencase"},
    }
    q_path.write_text(json.dumps(q, sort_keys=True) + "\n", encoding="utf-8")
    source_xml.write_text("<source/>\n", encoding="utf-8")
    source_control.write_text("time;ax\n0;0\n", encoding="utf-8")
    generated_xml.write_text(
        '<root><casedef><definition dp="0.015"><pointref x="0" y="0" z="0" /></definition></casedef>'
        '<particles nb="1" np="2"><fluid mkfluid="0" mk="1" begin="1" count="1" /></particles>'
        '<massfluid value="0.000216" /></root>\n', encoding="utf-8"
    )
    _vtk_points(fluid_vtk, with_idp=True, begin=1)
    _vtk_points(bound_vtk, with_idp=False)
    receipt = {
        "status": "completed", "returncode": 0, "output_root": str(actual_root),
        "request": q, "request_sha256": sha256(q_path),
        "input_hashes_at_launch": {str(source_control): sha256(source_control)},
        "input_hashes_after_run": {str(source_control): sha256(source_control)},
    }
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")

    # The frozen V3 contract only needs these records for its pre-read checks.
    contract = {
        "schema": "ds02.stage2.f3.s2.initial-support-contract.v3",
        "gencase_request": {"path": str(q_path), "sha256": sha256(q_path)},
        "gencase_receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)},
        "generated_xml": {"path": str(generated_xml), "sha256": sha256(generated_xml)},
        "source_xml": {"path": str(source_xml), "sha256": sha256(source_xml)},
        "source_control": {"path": str(source_control), "sha256": sha256(source_control)},
    }
    contract_path.write_text(json.dumps(contract, sort_keys=True) + "\n", encoding="utf-8")
    return argparse.Namespace(
        gencase_request=q_path, receipt=receipt_path, generated_xml=generated_xml,
        fluid_vtk=fluid_vtk, bound_vtk=bound_vtk, source_xml=source_xml,
        source_control=source_control, support_contract=contract_path, output=output,
        expected_generated_xml_sha=sha256(generated_xml), expected_support_contract_sha=sha256(contract_path),
    )


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="f3-v6-full-fixture-") as directory:
        args = _fixture_args(Path(directory))
        report = build_report(args)
        if report.get("status") != "COMPLETED_F3_S2_INITIAL_SUPPORT_AUDIT_V6":
            raise AssertionError(report.get("status"))
        stability = report.get("input_stability", {})
        if not stability.get("static_pre_post_identity_fields_only_equal"):
            raise AssertionError(stability)
        if stability.get("static_pre_post_descriptive_label_ignored") is not True:
            raise AssertionError(stability)
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "full_build_report_fixture": True,
        "static_identity_fields_only": list(STATIC_EQUALITY_FIELDS),
        "wrong_label_no_longer_fails": True,
        "solver_started": False,
        "bi4_read": False,
        "hdf5_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for name in ("gencase-request", "receipt", "generated-xml", "fluid-vtk", "bound-vtk", "source-xml", "source-control", "support-contract", "output"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--expected-generated-xml-sha")
    parser.add_argument("--expected-support-contract-sha")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    required = [args.gencase_request, args.receipt, args.generated_xml, args.fluid_vtk, args.bound_vtk, args.source_xml, args.source_control, args.support_contract, args.output]
    if any(value is None for value in required):
        parser.error("all q/receipt/generated/source/support-contract/output paths are required")
    report = build_report(args)
    write_new(args.output, report)
    print(json.dumps({"status": report["status"], "schema": SCHEMA, "output": str(args.output.resolve()), "static_identity_fields_only": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
