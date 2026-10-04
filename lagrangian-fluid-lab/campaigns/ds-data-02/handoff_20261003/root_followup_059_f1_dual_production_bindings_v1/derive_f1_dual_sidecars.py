#!/usr/bin/env python3
"""Attach actual Root strict-CPU sidecars to the F1 DUAL source manifest.

This is a metadata-only adapter.  It accepts a Root-owned worker result, checks
the bounded identity/check contract, and copies path/hash provenance into a
new manifest.  It never launches a solver and never reads or decodes BI4/XML
arrays, so it cannot manufacture a mass or evidence result.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_f1_dual_production_bindings import (
    attach_worker_outputs,
    load,
    refresh_request_bindings,
    save,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--audit-result", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--request",
        type=Path,
        help="Optional source request to refresh with actual worker sidecar bindings.",
    )
    args = parser.parse_args(argv)

    manifest = load(args.manifest)
    updated, sidecars = attach_worker_outputs(
        manifest,
        args.audit_result,
        output_dir=args.output_dir,
    )
    manifest_path = args.output_dir / "F1_DUAL_STAGE1_CASE_MANIFEST_WITH_WORKER_SIDECARS.json"
    save(manifest_path, updated)
    request_path = None
    if args.request is not None:
        request = refresh_request_bindings(load(args.request), updated)
        request_path = args.output_dir / "F1_DUAL_STAGE1_REQUEST_WITH_WORKER_SIDECARS.json"
        save(request_path, request)
    print(
        json.dumps(
            {
                "manifest": str(manifest_path.resolve()),
                "request": str(request_path.resolve()) if request_path is not None else None,
                "sidecar_count": len(sidecars),
                "source_only": True,
                "solver_launched": False,
                "raw_arrays_read": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
