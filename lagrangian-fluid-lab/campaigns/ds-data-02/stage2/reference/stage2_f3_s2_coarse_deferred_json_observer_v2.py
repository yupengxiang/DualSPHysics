#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""ROOT243 additive V2 deferred coarse-report worker.

The consumed V1 worker writes its compact report correctly but its CLI print
uses ``result["source"]["sha256"]`` even though the report provenance is
nested at ``result["source"]["report"]``.  ROOT243 therefore had a complete
compact output followed by a wrapper/CLI return-code failure.  This V2 keeps
the V1 parser and single-stream source guard unchanged, owns a new result
schema, and prints the nested provenance path that actually exists.  The
self-test invokes the real CLI entrypoint as a subprocess so this regression
cannot return.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import stage2_f3_s2_coarse_deferred_json_observer_v1 as legacy


SCHEMA = "ds02.stage2.f3-s2.coarse-deferred-json-observer.v2"
PASS_STATUS = "PASS_F3_COARSE_DEFERRED_JSON_COMPACT_V2"
FAIL_STATUS = "FAILED_F3_COARSE_DEFERRED_JSON_COMPACT_V2"


def run(report: Path, proof: Path, output: Path, queries: list[float]) -> dict[str, Any]:
    """Run the verified V1 source guard and emit only a new V2 envelope."""
    proof_value, binding, deferred = legacy._proof_binding(proof, report)
    report_value, report_record = legacy._read_report_once(report, deferred["report_sha256"], deferred["report_bytes"])
    source_record = {**deferred, **report_record, "proof": binding["proof"], "request": binding["request"], "receipt": binding["receipt"]}
    result = legacy.build_compact(report_value, source_record, queries)
    result["schema"] = SCHEMA
    result["status"] = PASS_STATUS
    result["compatibility"] = {
        "v1_parser_reused": True,
        "v1_output_cli_bug_fixed": True,
        "source_provenance_sha_path": "source.report.sha256",
        "v1_consumed_bytes_unchanged": True,
    }
    # legacy._atomic_json is still the V1 atomic writer; this output path is a
    # new V2 attempt path, so there is no overwrite of the consumed V1 file.
    legacy._atomic_json(output, result)
    return result


def _fixture() -> tuple[Path, Path, Path]:
    report, proof, output = legacy._fixture()
    return report, proof, output


def self_test() -> dict[str, Any]:
    report, proof, output = _fixture()
    result = run(report, proof, output, [0.0])
    if result["status"] != PASS_STATUS or result["source"]["report"]["sha256"] == "":
        raise AssertionError("V2 in-process worker result is incomplete")
    # Exercise the actual CLI print/return path.  This catches the exact
    # ROOT243 failure, which the old V1 self-test did not execute.
    cli_output = output.with_name("cli-output.json")
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--report", str(report), "--proof", str(proof), "--output", str(cli_output), "--query-times", "0"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not cli_output.is_file():
        raise AssertionError(f"V2 CLI failed: rc={completed.returncode}, stdout={completed.stdout!r}, stderr={completed.stderr!r}")
    printed = json.loads(completed.stdout)
    if printed.get("report_sha256") != result["source"]["report"]["sha256"]:
        raise AssertionError("V2 CLI printed the wrong nested report SHA")
    wrong = json.loads(proof.read_text(encoding="utf-8"))
    wrong["report_sha256"] = "0" * 64
    bad_proof = proof.with_name("bad-proof.json")
    bad_proof.write_text(json.dumps(wrong) + "\n", encoding="utf-8")
    try:
        run(report, bad_proof, output.with_name("bad-output.json"), [0.0])
    except ValueError:
        pass
    else:
        raise AssertionError("V2 accepted a wrong deferred-report SHA")
    return {"status": "PASS", "schema": SCHEMA, "actual_cli_exercised": True, "nested_report_sha_printed": True, "wrong_sha_rejected": True, "native_payload_read": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--proof", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--query-times", nargs="*", type=float, default=list(legacy.QUERY_TIMES_S))
    args = parser.parse_args(argv)
    if args.self_test:
        print(json.dumps(self_test(), sort_keys=True))
        return 0
    if args.report is None or args.proof is None or args.output is None:
        parser.error("--report, --proof, and --output are required")
    try:
        result = run(args.report, args.proof, args.output, args.query_times)
    except Exception as exc:
        print(f"{FAIL_STATUS}: {exc}")
        return 2
    report_record = result.get("source", {}).get("report")
    if not isinstance(report_record, dict) or not isinstance(report_record.get("sha256"), str):
        print(f"{FAIL_STATUS}: compact result lacks source.report.sha256")
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().resolve()), "report_sha256": report_record["sha256"], "frame_count": result["window"]["frame_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
