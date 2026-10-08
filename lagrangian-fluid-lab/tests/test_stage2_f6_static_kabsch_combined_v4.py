#!/usr/bin/env python3
"""Manufactured source/guard counterexamples for F6 combined-v4."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_f6_static_kabsch_combined_v4.py"
SPEC = importlib.util.spec_from_file_location("f6_combined_v4", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import F6 combined-v4 module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def expect_rejected(callback, label: str) -> None:
    try:
        callback()
    except MODULE.CombinedV4Error:
        return
    raise AssertionError(f"manufactured {label} was accepted")


def main() -> int:
    source_bundle = MODULE.V3_BUNDLE_DEFAULT
    source_request = MODULE.V3_REQUEST_DEFAULT
    with tempfile.TemporaryDirectory(prefix="ds02-f6-combined-v4-tests-") as directory:
        root = Path(directory)
        manifest_path = root / "bundle.json"
        request_path = root / "request.json"
        original_sha256 = MODULE.sha256

        def reject_h5_prepare_hash(path):
            if Path(path).name == "trajectory.h5":
                raise AssertionError("v4 prepare attempted a new H5 content hash")
            return original_sha256(path)

        MODULE.sha256 = reject_h5_prepare_hash
        try:
            prepared = MODULE.prepare(source_bundle, source_request, manifest_path, request_path)
        finally:
            MODULE.sha256 = original_sha256
        assert prepared["status"] == "prepared"
        assert prepared["shared_runtime"] == "v6"
        assert prepared["launch_allowed"] is False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        request = json.loads(request_path.read_text(encoding="utf-8"))
        assert manifest["schema"] == MODULE.V4_BUNDLE_SCHEMA
        assert manifest["runtime_stack"]["v6_entry_is_the_only_ledger_owner"] is True
        assert request["shared_runtime_version"] == "v6"
        assert request["runtime_binding"]["path"].endswith("ds_data02_runtime_v6.py")
        assert request["dispatch_binding"]["path"].endswith("ds_data02_stage2_dispatch_v6.py")
        assert request["strict_dispatch_binding"]["path"].endswith("ds_data02_strict_dispatch_v6.py")
        assert all(path in request["input_files"] for path in (
            request["runtime_binding"]["path"], request["dispatch_binding"]["path"],
            request["strict_dispatch_binding"]["path"],
        ))
        assert all("trajectory.h5" not in path or request["input_sha256"][path] == row["trajectory_h5_sha256"]
                   for path in request["input_files"]
                   for row in request["source_cases"] if path == row["trajectory_h5_path"])
        assert manifest["hash_ownership"]["h5_content_hashed_during_prepare"] is False
        assert manifest["hash_ownership"]["owner"] == "single_combined_v4_attempt"

        # A small manufactured completed receipt exercises the source/runner
        # identity gate without opening either H5 or fabricating Kabsch data.
        output_path = root / "output.json"
        output = {
            "schema": MODULE.V4_OUTPUT_SCHEMA,
            "status": "completed",
            "bundle": {"path": str(manifest_path.resolve()), "sha256": MODULE.sha256(manifest_path)},
            "cases": [{
                "physical_case_id": row["physical_case_id"],
                "h5_read_ledger": {"opened_once": True},
                "static": {"trajectory": {"frame_datasets_read": True}},
                "kabsch": {"status": "completed", "frozen_contract": {"so3_error_tolerances_deg": {"rmse": 2.0, "max": 5.0}}},
                "conversion_object_source": "loaded_from_exact_v4_report_binding_in_worker",
            } for row in manifest["source_cases"]],
        }
        output_path.write_text(json.dumps(output), encoding="utf-8")
        receipt_path = root / "receipt.json"
        receipt = {
            "schema": "ds02.execution-receipt.v1", "status": "completed", "returncode": 0,
            "runner_source": request["runtime_binding"]["path"],
            "runner_sha256": request["runtime_binding"]["sha256"],
            "request": request,
            "input_hashes_at_launch": request["input_sha256"],
            "input_hashes_after_run": request["input_sha256"],
        }
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        checked = MODULE.validate(manifest_path, output_path, receipt_path)
        assert checked["status"] == "completed"
        bad_receipt = copy.deepcopy(receipt)
        bad_receipt["request"]["shared_runtime_version"] = "v4"
        bad_receipt_path = root / "bad-receipt.json"
        bad_receipt_path.write_text(json.dumps(bad_receipt), encoding="utf-8")
        expect_rejected(lambda: MODULE.validate(manifest_path, output_path, bad_receipt_path), "wrong shared runtime version")

        row = manifest["source_cases"][0]
        unbound = copy.deepcopy(row)
        unbound["conversion"] = {"conversion_status": "completed"}
        expect_rejected(lambda: MODULE.validate_v4_row_shape(unbound), "row conversion injection")

        missing_contract = copy.deepcopy(row)
        missing_contract.pop("conversion_contract")
        expect_rejected(lambda: MODULE.validate_v4_row_shape(missing_contract), "missing conversion contract")

        wrong_report_sha = copy.deepcopy(row)
        wrong_report_sha["conversion_contract"]["report"]["sha256"] = "0" * 64
        expect_rejected(lambda: MODULE.load_conversion(wrong_report_sha), "wrong conversion report SHA")

        wrong_h5_sha = copy.deepcopy(row)
        wrong_h5_sha["conversion_contract"]["output_hdf5"]["sha256"] = "0" * 64
        expect_rejected(lambda: MODULE.load_conversion(wrong_h5_sha), "wrong output H5 SHA")

        wrong_h5_path = copy.deepcopy(row)
        wrong_h5_path["trajectory_h5"]["path"] = str(root / "other-trajectory.h5")
        expect_rejected(lambda: MODULE.load_conversion(wrong_h5_path), "wrong output H5 path")

        bad_bundle_path = root / "bad-bundle.json"
        bad_bundle = json.loads(source_bundle.read_text(encoding="utf-8"))
        bad_bundle["schema"] = "ds02.stage2.f6-static-kabsch-combined-bundle.v999"
        bad_bundle_path.write_text(json.dumps(bad_bundle), encoding="utf-8")
        expect_rejected(lambda: MODULE._validate_v3_source(bad_bundle_path, source_request), "wrong consumed v3 schema")

        bad_request_path = root / "bad-request.json"
        bad_request = json.loads(source_request.read_text(encoding="utf-8"))
        bad_request["input_sha256"][str(source_bundle.resolve())] = "0" * 64
        bad_request_path.write_text(json.dumps(bad_request), encoding="utf-8")
        expect_rejected(lambda: MODULE._validate_v3_source(source_bundle, bad_request_path), "wrong consumed v3 bundle digest")

        bad_runtime_request = copy.deepcopy(request)
        bad_runtime_request["shared_runtime_version"] = "v4"
        assert bad_runtime_request["shared_runtime_version"] != "v6"

    print("stage2 F6 combined-v4 shared-v6/source/H5 counterexamples: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
