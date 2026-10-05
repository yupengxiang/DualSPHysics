#!/usr/bin/env python3
"""Metadata-only contract preflight for the real export_xmf.py worker.

This module never opens a trajectory, BI4, VTK, CSV, DAT, or H5 payload.  It
only validates caller-supplied JSON metadata and path strings.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping

HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
STALE_MARKERS = ("fresh104", "fresh105", "fresh097", "fresh098", "fresh099")
WAIT_STATUSES = {"WAIT", "WAIT_ROOT648", "WAIT_ROOT648_TYPED_COMPLETION", "WAIT_ROOT648_PER_CASE_COMPLETED0_AND_REPORT_PASS"}
READY_STATUSES = {"COMPLETED", "COMPLETED/0", "COMPLETED/0_AND_REPORT_PASS", "READY", "READY_FOR_ROOT_EXPORTER"}

class BindingContractError(ValueError):
    """Raised when a metadata binding cannot be passed to export_xmf.py."""

def _fail(message: str) -> None:
    raise BindingContractError(message)

def _hex64(value: Any, field: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        _fail(f"{field} must be a 64-hex metadata digest")
    return value

def _absolute_string(value: Any, field: str, *, marker: str | None = None) -> str:
    if not isinstance(value, str):
        _fail(f"{field} must be an absolute string path; nested path dictionaries are rejected")
    path = Path(value)
    if not path.is_absolute():
        _fail(f"{field} must be absolute: {value!r}")
    lowered = value.lower()
    if any(item in lowered for item in STALE_MARKERS):
        _fail(f"{field} points at a stale/future source path: {value}")
    if marker and marker not in lowered:
        _fail(f"{field} is not bound to the required {marker} actual output: {value}")
    return value

def _scope(binding: Mapping[str, Any], *, ready: bool) -> Mapping[str, Any]:
    scope = binding.get("physical_scope")
    if not isinstance(scope, Mapping):
        _fail("physical_scope must be a metadata object")
    if scope.get("source_owner_hash_reused") is not False:
        _fail("physical_scope must explicitly keep source-owner hash separate")
    legacy = scope.get("legacy_owner_scope_sha256")
    actual = scope.get("actual_scope_sha256")
    if legacy is None and actual is None:
        _fail("physical_scope has no converter-scope digest")
    if legacy is not None:
        _hex64(legacy, "physical_scope.legacy_owner_scope_sha256")
    if actual is not None:
        _hex64(actual, "physical_scope.actual_scope_sha256")
    if ready and actual is None:
        _fail("completed Root648 binding needs actual_scope_sha256")
    owner = binding.get("physical_binding")
    if not isinstance(owner, Mapping):
        _fail("physical_binding metadata sidecar is required")
    _absolute_string(owner.get("path"), "physical_binding.path")
    _hex64(owner.get("sha256"), "physical_binding.sha256")
    if ready and scope.get("status") not in (None, "completed", "completed/0", "actual_confirmed"):
        _fail("completed binding still advertises a pending physical scope")
    return scope

def _native_path(binding: Mapping[str, Any]) -> str:
    value = _absolute_string(binding.get("native_receipt"), "native_receipt")
    if "root619" not in value.lower():
        _fail("native_receipt must be the actual Root619 receipt, not a future/native replacement")
    return value

def _report_metadata(binding: Mapping[str, Any], report: Mapping[str, Any] | None) -> Mapping[str, Any]:
    selected = report
    if selected is None:
        candidate = binding.get("actual_conversion_report")
        selected = candidate if isinstance(candidate, Mapping) else None
    if not isinstance(selected, Mapping):
        _fail("completed Root648 binding needs caller-supplied conversion report metadata")
    if selected.get("conversion_status") != "completed":
        _fail("conversion report is not completed")
    if selected.get("returncode") not in (None, 0):
        _fail("conversion report returncode is not zero")
    if selected.get("frames") != 1201:
        _fail("conversion report does not contain 1201 frames")
    particles = selected.get("particles")
    if not isinstance(particles, int) or particles <= 0:
        _fail("conversion report particles must be positive")
    partvtk = selected.get("partvtk_validation")
    if not isinstance(partvtk, Mapping) or partvtk.get("all_passed") is not True:
        _fail("conversion report does not attest PartVTK validation")
    h5_digest = next((selected.get(key) for key in ("producer_h5_sha256", "trajectory_h5_sha256", "h5_sha256") if selected.get(key) is not None), None)
    _hex64(h5_digest, "conversion report producer_h5_sha256")
    report_condition = selected.get("physical_condition_sha256")
    if report_condition is not None:
        _hex64(report_condition, "conversion report physical_condition_sha256")
        if report_condition != binding.get("physical_condition_sha256"):
            _fail("conversion report physical condition differs from binding")
    return selected

def preflight_binding(binding: Mapping[str, Any], *, typed_status: str | None = None, conversion_report: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate one metadata binding without reading any referenced path.

    WAIT bindings contain null future typed/report/H5 values.  A completed
    binding contains absolute strings because that is what export_xmf.py
    passes to ``Path(...)``.  The function intentionally does not test that
    paths exist: Root's registered worker owns that filesystem operation.
    """
    if not isinstance(binding, Mapping):
        _fail("binding must be a JSON object")
    if binding.get("expected_frames") != 1201:
        _fail("expected_frames must equal 1201")
    if binding.get("physical_window_s") != [0.0, 1.2]:
        _fail("physical_window_s must equal [0.0, 1.2]")
    case_id = binding.get("physical_case_id") or binding.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        _fail("physical_case_id is required")
    _hex64(binding.get("physical_condition_sha256"), "physical_condition_sha256")
    status = str(typed_status if typed_status is not None else binding.get("typed_status", "WAIT")).upper()
    is_wait = status in WAIT_STATUSES or status.startswith("WAIT")
    is_ready = status in READY_STATUSES or status.startswith("COMPLETED") or status.startswith("READY")
    if not (is_wait or is_ready):
        _fail(f"unsupported typed status: {status}")
    _scope(binding, ready=is_ready)
    native = _native_path(binding)
    if is_wait:
        # Future output fields must remain null.  This also rejects nested
        # {path,sha256} dictionaries instead of quietly unwrapping them.
        for key in ("typed_receipt", "conversion_report", "trajectory_h5"):
            if binding.get(key) is not None:
                _fail(f"WAIT binding requires {key}=null; future paths/dictionaries are rejected")
        return {"status": "WAIT_ROOT648_TYPED_COMPLETION", "physical_case_id": case_id, "native_receipt": native}
    typed = _absolute_string(binding.get("typed_receipt"), "typed_receipt", marker="root648")
    report_path = _absolute_string(binding.get("conversion_report"), "conversion_report", marker="root648")
    trajectory = _absolute_string(binding.get("trajectory_h5"), "trajectory_h5", marker="root648")
    if not trajectory.lower().endswith((".h5", ".hdf5")):
        _fail("trajectory_h5 must name an H5 output")
    _scope(binding, ready=True)
    report = _report_metadata(binding, conversion_report)
    return {"status": "READY_FOR_ROOT_EXPORTER", "physical_case_id": case_id, "typed_receipt": typed, "native_receipt": native, "conversion_report": report_path, "trajectory_h5": trajectory, "frames": report["frames"], "particles": report["particles"]}

def _base(native: str) -> dict[str, Any]:
    return {
        "schema": "ds02.f4.fresh106.export-xmf-binding.v1",
        "case_id": "SYNTHETIC_CASE",
        "physical_case_id": "SYNTHETIC_CASE",
        "physical_condition_sha256": "c" * 64,
        "physical_scope": {"scope_kind": "root648_actual_legacy_owner_scope", "legacy_owner_scope_sha256": "a" * 64, "actual_scope_sha256": None, "source_owner_hash_reused": False, "status": "pending"},
        "physical_binding": {"path": "/metadata/owner.json", "sha256": "d" * 64},
        "native_receipt": native,
        "expected_frames": 1201,
        "physical_window_s": [0.0, 1.2],
        "typed_receipt": None,
        "conversion_report": None,
        "trajectory_h5": None,
    }

def run_synthetic_tests() -> list[str]:
    native = "/data/root-stage1-f4-synthetic-root619/execution-receipt.json"
    result = []
    wait = preflight_binding(_base(native), typed_status="WAIT")
    assert wait["status"].startswith("WAIT")
    result.append("valid WAIT with null future outputs")
    bad = _base(native); bad["typed_receipt"] = {"path": "/data/root648/execution-receipt.json", "sha256": None}
    try: preflight_binding(bad, typed_status="WAIT")
    except BindingContractError: result.append("nested path dictionary rejected")
    else: raise AssertionError("nested dictionary was accepted")
    bad = _base(native); bad["typed_receipt"] = "/data/fresh104/execution-receipt.json"
    try: preflight_binding(bad, typed_status="WAIT")
    except BindingContractError: result.append("future WAIT path rejected")
    else: raise AssertionError("future WAIT path was accepted")
    bad = _base(native); bad["native_receipt"] = {"path": native}
    try: preflight_binding(bad, typed_status="WAIT")
    except BindingContractError: result.append("native path dictionary rejected")
    else: raise AssertionError("native dictionary was accepted")
    bad = _base(native); bad.update({"typed_receipt": "/data/root648/execution-receipt.json", "conversion_report": "/data/root648/conversion-report.json", "trajectory_h5": "/data/root648/trajectory.h5"})
    bad["physical_scope"]["actual_scope_sha256"] = "b" * 64; bad["physical_scope"]["status"] = "actual_confirmed"
    try: preflight_binding(bad, typed_status="COMPLETED/0")
    except BindingContractError: result.append("completed binding without report rejected")
    else: raise AssertionError("missing report was accepted")
    complete = _base(native)
    complete.update({"typed_receipt": "/data/root-stage1-f4-synthetic-root648/execution-receipt.json", "conversion_report": "/data/root-stage1-f4-synthetic-root648/conversion-report.json", "trajectory_h5": "/data/root-stage1-f4-synthetic-root648/trajectory.h5"})
    complete["physical_scope"].update({"actual_scope_sha256": "c" * 64, "status": "actual_confirmed"})
    report = {"conversion_status": "completed", "returncode": 0, "frames": 1201, "particles": 83233, "partvtk_validation": {"all_passed": True}, "producer_h5_sha256": "e" * 64, "physical_condition_sha256": "c" * 64}
    ready = preflight_binding(complete, typed_status="COMPLETED/0", conversion_report=report)
    assert ready["status"] == "READY_FOR_ROOT_EXPORTER"
    result.append("actual Root648 completed/0 report accepted")
    bad = dict(complete); bad["native_receipt"] = "/data/fresh104/execution-receipt.json"
    try: preflight_binding(bad, typed_status="COMPLETED/0", conversion_report=report)
    except BindingContractError: result.append("stale native source rejected")
    else: raise AssertionError("stale native source was accepted")
    return result

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--binding", type=Path)
    ap.add_argument("--typed-status")
    ap.add_argument("--report-json", type=Path, help="metadata JSON only; never a scientific payload")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        print("fresh106 synthetic preflight: PASS (" + "; ".join(run_synthetic_tests()) + ")")
        return
    if args.binding is None:
        ap.error("--binding is required unless --self-test is used")
    binding = json.loads(args.binding.read_text(encoding="utf-8"))
    report = json.loads(args.report_json.read_text(encoding="utf-8")) if args.report_json else None
    print(json.dumps(preflight_binding(binding, typed_status=args.typed_status, conversion_report=report), indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
