#!/usr/bin/env python3
"""Metadata-only verifier for actual Root189/XMF receipts.

This imports the fresh078 assembler, which deliberately rejects BI4, H5 and
CSV paths in metadata input sets and uses the converter report's verified H5
SHA instead of opening the H5.  It is safe to run before or after Root jobs;
it never launches a process.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from assemble_post_conversion_pipeline import (
    DEFAULT_FRESH077_ROOT,
    verify_fresh077_sources,
    verify_typed_conversion,
    verify_xmf_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh077-root", type=Path, default=DEFAULT_FRESH077_ROOT)
    parser.add_argument("--typed-receipt", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path, required=True)
    parser.add_argument("--xmf-receipt", type=Path)
    parser.add_argument("--xmf-dir", type=Path)
    args = parser.parse_args()
    fresh077 = args.fresh077_root.resolve()
    verify_fresh077_sources(fresh077)
    typed = verify_typed_conversion(args.typed_receipt, args.conversion_report)
    result = {
        "schema": "ds02.f5.b071.post-conversion-metadata-verification.v1",
        "source_only": True,
        "arrays_opened": False,
        "jobs_started": False,
        "typed_receipt": str(typed["receipt_path"]),
        "typed_receipt_sha256": typed["receipt_sha256"],
        "conversion_report": str(typed["report_path"]),
        "conversion_report_sha256": typed["report_sha256"],
        "trajectory_h5": str(typed["trajectory_h5"]),
        "trajectory_h5_sha256_from_report": typed["trajectory_h5_sha256"],
        "native_bed_marker_mk": 50,
        "full801_authorized": False,
    }
    if bool(args.xmf_receipt) != bool(args.xmf_dir):
        raise ValueError("--xmf-receipt and --xmf-dir must be supplied together")
    if args.xmf_receipt:
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
