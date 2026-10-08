#!/usr/bin/env python3
"""Counterexamples for the F6 combined-v3 conversion/source contract."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_f6_static_kabsch_combined_v3.py"
SPEC = importlib.util.spec_from_file_location("f6_combined_v3", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import F6 combined-v3 module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def expect_rejected(callback, label: str) -> None:
    try:
        callback()
    except MODULE.CombinedV3Error:
        return
    raise AssertionError(f"manufactured {label} was accepted")


def main() -> int:
    bundle_path = MODULE.V2_BUNDLE_DEFAULT
    receipt_path = MODULE.V2_RECEIPT_DEFAULT
    stdout_path = MODULE.V2_STDOUT_DEFAULT
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    request_path = MODULE.locate_v2_request(receipt, None)
    failure = MODULE.validate_consumed_failure(
        bundle_path,
        bundle,
        request_path,
        receipt_path,
        receipt,
        stdout_path,
    )
    assert failure["status"] == "failed_before_worker_h5_open"
    assert failure["receipt_request_sha256"] != failure["source_request_sha256"]
    assert len(failure["h5_terminal_bindings"]) == 2
    for row in bundle["source_cases"]:
        contract = MODULE.conversion_contract(row)
        assert contract["schema"] == MODULE.CONVERSION_CONTRACT_SCHEMA
        assert contract["output_hdf5"]["sha256"] == row["trajectory_h5"]["sha256"]

    with tempfile.TemporaryDirectory(prefix="ds02-f6-combined-v3-tests-") as directory:
        root = Path(directory)
        manifest_path = root / "bundle.json"
        request_out = root / "request.json"
        original_sha256 = MODULE.sha256

        def reject_h5_prepare_hash(path):
            if Path(path).name == "trajectory.h5":
                raise AssertionError("v3 prepare attempted a new H5 content hash")
            return original_sha256(path)

        MODULE.sha256 = reject_h5_prepare_hash
        try:
            prepared = MODULE.prepare(
                bundle_path,
                request_path,
                receipt_path,
                stdout_path,
                manifest_path,
                request_out,
            )
        finally:
            MODULE.sha256 = original_sha256
        assert prepared["status"] == "prepared"
        prepared_bundle = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = prepared_bundle["source_cases"]
        assert all("conversion" not in row for row in rows)
        assert all(row["conversion_contract"]["schema"] == MODULE.CONVERSION_CONTRACT_SCHEMA for row in rows)
        assert prepared_bundle["hash_ownership"]["h5_content_hashed_during_prepare"] is False

        row = rows[0]
        unbound = copy.deepcopy(row)
        unbound["conversion"] = {"conversion_status": "completed"}
        expect_rejected(lambda: MODULE.validate_v3_row_shape(unbound), "row conversion injection")

        missing_contract = copy.deepcopy(row)
        missing_contract.pop("conversion_contract")
        expect_rejected(lambda: MODULE.validate_v3_row_shape(missing_contract), "missing conversion contract")

        wrong_report_sha = copy.deepcopy(row)
        wrong_report_sha["conversion_contract"]["report"]["sha256"] = "0" * 64
        expect_rejected(lambda: MODULE.load_conversion(wrong_report_sha), "wrong conversion report SHA")

        wrong_h5_sha = copy.deepcopy(row)
        wrong_h5_sha["conversion_contract"]["output_hdf5"]["sha256"] = "0" * 64
        expect_rejected(lambda: MODULE.load_conversion(wrong_h5_sha), "wrong output H5 SHA")

        wrong_h5_path = copy.deepcopy(row)
        wrong_h5_path["trajectory_h5"]["path"] = str(root / "other-trajectory.h5")
        expect_rejected(lambda: MODULE.load_conversion(wrong_h5_path), "wrong output H5 path")

        changed_report_path = root / "changed-conversion-report.json"
        source_report = Path(row["conversion_contract"]["report"]["path"])
        changed_report = json.loads(source_report.read_text(encoding="utf-8"))
        changed_report["conversion_status"] = "failed"
        changed_report_path.write_text(json.dumps(changed_report), encoding="utf-8")
        failed_report = copy.deepcopy(row)
        failed_report["conversion_contract"]["report"] = {
            "path": str(changed_report_path),
            "sha256": MODULE.sha256(changed_report_path),
            "bytes": changed_report_path.stat().st_size,
        }
        expect_rejected(lambda: MODULE.load_conversion(failed_report), "non-completed conversion report")

        wrong_solver = copy.deepcopy(row)
        wrong_solver["conversion_contract"]["source_provenance"]["solver_receipt"]["sha256"] = "0" * 64
        expect_rejected(lambda: MODULE.load_conversion(wrong_solver), "wrong solver receipt binding")

        wrong_source_bundle = copy.deepcopy(bundle)
        wrong_source_bundle["source_cases"][0]["trajectory_h5"]["sha256"] = "0" * 64
        expect_rejected(
            lambda: MODULE.validate_consumed_failure(
                bundle_path,
                wrong_source_bundle,
                request_path,
                receipt_path,
                receipt,
                stdout_path,
            ),
            "wrong consumed H5 digest",
        )

    print("stage2 F6 combined-v3 conversion/source/terminal counterexamples: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
