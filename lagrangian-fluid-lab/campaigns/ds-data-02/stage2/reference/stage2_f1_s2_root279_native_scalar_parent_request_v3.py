#!/usr/bin/env python3
"""Source-only ROOT279 request builder for scalar parent worker V3.

This is an additive overlay over the consumed V2 builder.  It changes only the
parent/compact worker source bindings and request variant; ROOT277/278/310
proof joins, literal venv invocation, deferred native records, and the
execution-disabled policy remain inherited from V2.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
V2_PATH = HERE / "stage2_f1_s2_root279_native_scalar_parent_request_v2.py"
PARENT_V3 = HERE / "stage2_f1_s2_root279_native_scalar_parent_worker_v3.py"
COMPACT_V3 = HERE / "stage2_f1_s2_root279_native_compact_worker_v3.py"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.root279-native-scalar-parent-request.v3"
PARENT_MANIFEST_SCHEMA = "ds02.stage2.f1-s2.root279-native-scalar-parent-manifest.v3"

SPEC = importlib.util.spec_from_file_location("root279_parent_request_v2_for_v3", V2_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load scalar parent request V2: {V2_PATH}")
V2 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(V2)


class BuildV3Failure(RuntimeError):
    pass


def _configure() -> None:
    # V2 builder's _augment consults these module globals and V2's imported V1
    # builder globals.  All replacements are additive and source-hashed.
    V2.PARENT_V2 = PARENT_V3
    V2.COMPACT_V2 = COMPACT_V3
    V2.VARIANT_SCHEMA = VARIANT_SCHEMA
    V2.PARENT_MANIFEST_SCHEMA = PARENT_MANIFEST_SCHEMA
    V2.V1.PARENT_WORKER = PARENT_V3
    V2.V1.COMPACT = COMPACT_V3
    V2.V1.VARIANT_SCHEMA = VARIANT_SCHEMA
    V2.V1.PARENT_MANIFEST_SCHEMA = PARENT_MANIFEST_SCHEMA


def build(args: argparse.Namespace) -> dict[str, Any]:
    _configure()
    result = V2.build(args)
    result = dict(result)
    result["variant_schema"] = VARIANT_SCHEMA
    result["parent_worker_sha256"] = result.get("request", {}).get("source_binding", {}).get("parent_worker_sha256")
    result["compact_worker_sha256"] = result.get("request", {}).get("source_binding", {}).get("compact_worker_sha256")
    return result


def _self_test() -> None:
    _configure()
    assert V2.V1.PARENT_WORKER == PARENT_V3
    assert V2.V1.COMPACT == COMPACT_V3
    assert V2.VARIANT_SCHEMA == VARIANT_SCHEMA
    assert V2.PARENT_MANIFEST_SCHEMA == PARENT_MANIFEST_SCHEMA
    print("PASS_ROOT279_PARENT_REQUEST_V3_BINDS_ACTUAL_GUARD_STATUS_COMPATIBILITY_WORKER")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build", action="store_true")
    parser.add_argument("--root279-manifest", type=Path); parser.add_argument("--root279-request", type=Path)
    parser.add_argument("--same-proof", type=Path); parser.add_argument("--half-proof", type=Path)
    parser.add_argument("--root310-proof", type=Path); parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--cwd", type=Path, default=HERE.parents[5])
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        required = (args.root279_manifest, args.root279_request, args.same_proof,
                    args.half_proof, args.root310_proof, args.output_dir)
        if any(item is None for item in required):
            parser.error("--build requires ROOT279 manifest/request, ROOT277/278 proofs, ROOT310 proof and output directory")
        value = build(args)
        print(json.dumps({"status": "SOURCE_PREPARED_WAITING_PARENT_ROOT279_NATIVE_CHAIN_V3",
                          "manifest": value["manifest_path"], "request": value["request_path"],
                          "package": value["package_path"], "scientific_credit": 0}, sort_keys=True)); return 0
    except (BuildV3Failure, V2.BuildV2Failure, V2.V1.BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_NATIVE_SCALAR_PARENT_REQUEST_V3: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
