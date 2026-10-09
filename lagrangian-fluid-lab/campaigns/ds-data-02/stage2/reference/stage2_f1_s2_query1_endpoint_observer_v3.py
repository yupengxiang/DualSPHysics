#!/usr/bin/env python3
"""ROOT232 query-1 wrapper around the axis-independent ROOT231 reader.

This is a new namespace.  It changes only the frozen query set to 1 s and
the output schema; ROOT225 and ROOT231 worker bytes are never edited.
"""

from __future__ import annotations

import argparse

import stage2_f1_s2_query_endpoint_observer_v2 as _v2


SCHEMA = "ds02.stage2.f1-s2.query1-endpoint-observer.v3"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.query1-endpoint-manifest.v2"
PASS_STATUS = "COMPLETE_QUERY1_NATIVE_COMPONENT_DIAGNOSTICS_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_QUERY1_NATIVE_ENDPOINT_GUARD"
QUERY_TIMES_S = (1.0,)


def _configure() -> None:
    # The imported implementation is pure source/metadata code; setting its
    # module constants before run() gives this namespace its own schema and
    # query contract without changing the consumed ROOT231 module.
    _v2.SCHEMA = SCHEMA
    _v2.MANIFEST_SCHEMA = MANIFEST_SCHEMA
    _v2.PASS_STATUS = PASS_STATUS
    _v2.FAIL_STATUS = FAIL_STATUS
    _v2.QUERY_TIMES_S = QUERY_TIMES_S


def run(args):
    _configure()
    return _v2.run(args)


def self_test() -> None:
    _configure()
    _v2.self_test.__globals__["QUERY_TIMES_S"] = QUERY_TIMES_S
    # Verify the actual inherited component-space reader with its manufactured
    # decoder fixture; it must not require axis source records.
    import json
    import tempfile
    from pathlib import Path

    import stage2_f1_native_selected_observer_v1 as calibrated

    with tempfile.TemporaryDirectory(prefix="root232-query1-") as temporary:
        root = Path(temporary)
        manifest = calibrated._fixture_manifest(root / "fixture")
        case = json.loads(manifest.read_text(encoding="utf-8"))["cases"][0]
        case["query_times"] = [0.0, 0.5]
        result = calibrated._case_result(case, {"status": "AXIS_UNKNOWN"}, root / "attempt")
        assert result["native_summary"]["MassFluid_kg"] == 2.0
    print("PASS_F1_S2_QUERY1_ENDPOINT_OBSERVER_V3_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest")
    parser.add_argument("--attempt-root")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not (args.manifest and args.attempt_root and args.output):
        parser.error("--manifest, --attempt-root, and --output are required unless --self-test is used")
    from pathlib import Path
    try:
        result = run(argparse.Namespace(manifest=Path(args.manifest), attempt_root=Path(args.attempt_root), output=Path(args.output)))
    except Exception as exc:
        _configure()
        _v2._failure_report_v2(Path(args.output), str(exc))
        print(f"FAIL_F1_S2_QUERY1_ENDPOINT_OBSERVER_V3: {exc}")
        return 2
    import json
    print(json.dumps({"status": result["status"], "output": str(Path(args.output).absolute())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
