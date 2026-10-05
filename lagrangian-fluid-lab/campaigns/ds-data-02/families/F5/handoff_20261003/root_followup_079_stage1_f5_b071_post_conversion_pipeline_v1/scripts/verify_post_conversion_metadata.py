#!/usr/bin/env python3
"""Metadata-only verifier for the real Root189/XMF producer shapes.

The request-only mode validates the enabled integration request before the CPU
slot runs. The receipt/report mode validates the completed producer metadata.
It never opens BI4, H5, or CSV scientific arrays and never launches a job.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from assemble_post_conversion_pipeline import (
    DEFAULT_FRESH077_ROOT,
    json_sha,
    verify_fresh077_sources,
    verify_typed_conversion,
    verify_typed_request_shape,
    verify_xmf_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh077-root", type=Path, default=DEFAULT_FRESH077_ROOT)
    parser.add_argument("--typed-request", type=Path)
    parser.add_argument("--typed-receipt", type=Path)
    parser.add_argument("--conversion-report", type=Path)
    parser.add_argument("--xmf-receipt", type=Path)
    parser.add_argument("--xmf-dir", type=Path)
    args = parser.parse_args()
    if bool(args.typed_receipt) != bool(args.conversion_report):
        raise ValueError("--typed-receipt and --conversion-report must be supplied together")
    if not args.typed_request and not args.typed_receipt:
        raise ValueError("provide --typed-request or the completed receipt/report pair")
    if bool(args.xmf_receipt) != bool(args.xmf_dir):
        raise ValueError("--xmf-receipt and --xmf-dir must be supplied together")

    fresh077 = args.fresh077_root.resolve()
    verify_fresh077_sources(fresh077)
    result = {
        "schema": "ds02.f5.b071.fresh079.post-conversion-metadata-verification.v1",
        "source_only": True,
        "arrays_opened": False,
        "jobs_started": False,
        "native_bed_marker_mk": 50,
        "full801_authorized": False,
    }
    if args.typed_request:
        request = verify_typed_request_shape(args.typed_request.resolve())
        result.update({
            "typed_request": str(args.typed_request.resolve()),
            "typed_request_sha256": json_sha(args.typed_request.resolve()),
            "typed_request_shape": "actual_root189_enabled_request",
            "typed_expected_particles": request["expected_particles"],
            "typed_expected_fluid_particles": request["expected_fluid_particles"],
        })
    typed = None
    if args.typed_receipt:
        typed = verify_typed_conversion(args.typed_receipt, args.conversion_report)
        result.update({
            "typed_receipt": str(typed["receipt_path"]),
            "typed_receipt_sha256": typed["receipt_sha256"],
            "conversion_report": str(typed["report_path"]),
            "conversion_report_sha256": typed["report_sha256"],
            "trajectory_h5": str(typed["trajectory_h5"]),
            "trajectory_h5_sha256_from_report": typed["trajectory_h5_sha256"],
            "typed_product_shape": "actual_completed_conversion_report",
        })
    if bool(args.xmf_receipt):
        if typed is None:
            raise ValueError("XMF verification also requires the completed typed receipt/report pair")
        xmf = verify_xmf_receipt(args.xmf_receipt, args.xmf_dir, typed)
        result.update({
            "xmf_receipt": str(xmf["receipt_path"]),
            "xmf_receipt_sha256": xmf["receipt_sha256"],
            "xmf": str(xmf["xmf_path"]),
            "xmf_sha256": xmf["xmf_sha256"],
            "xmf_manifest": str(xmf["manifest_path"]),
            "xmf_manifest_sha256": xmf["manifest_sha256"],
            "downstream_bindings_ready": True,
        })
    else:
        result["downstream_bindings_ready"] = False
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
