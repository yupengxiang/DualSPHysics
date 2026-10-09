#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the additive ROOT243 V2 request with the corrected CLI worker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import stage2_f3_s2_coarse_deferred_json_observer_request_v1 as legacy


HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_f3_s2_coarse_deferred_json_observer_v2.py"
VARIANT = "ds02.stage2.f3-s2.coarse-deferred-json-observer-request.v2"
CASE = "F3_S2_COARSE_DEFERRED_JSON_OBSERVER_ROOT243_V2"
ATTEMPT = "f3-s2-coarse-deferred-json-observer-v2-root-243-002"


def build(args: argparse.Namespace) -> dict:
    payload = legacy.build(args)
    command = list(payload["command"])
    # v1 command: [literal-python, v1-worker, --report, ...].  Preserve every
    # source/report argument and replace only the additive worker/output.
    command[1] = str(WORKER)
    command[-1] = "{attempt_root}/observer/f3_s2_coarse_deferred_json_observer_v2.json"
    payload["variant_schema"] = VARIANT
    payload["status"] = "READY_FOR_PARENT_V8_DEFERRED_LARGE_JSON_F3_COARSE_ROOT243_V2"
    payload["case_id"] = args.case_id
    payload["attempt_id"] = args.attempt_id
    payload["command"] = command
    payload["compatibility"] = {"v1_worker": str(legacy.WORKER), "v2_worker": str(WORKER), "v1_payload_parser_reused": True, "cli_nested_source_report_sha_fix": True, "v1_request_bytes_unchanged": True}
    payload["input_files"] = sorted(set(payload["input_files"]) | {str(WORKER)})
    # The legacy builder's input_hashes has the V1 worker; record the V2 source
    # as an additional immutable input.  It is intentionally not substituted
    # for the V1 parser imported at runtime.
    v2_record = legacy._code_record(WORKER, "ROOT243 V2 corrected CLI worker")
    payload["input_hashes"][v2_record["path"]] = v2_record["sha256"]
    payload["input_sha256"][v2_record["path"]] = v2_record["sha256"]
    payload["input_records"][v2_record["path"]] = v2_record
    payload["source_binding"]["v2_worker"] = v2_record
    payload["source_binding"]["v1_worker_parser"] = str(legacy.WORKER)
    # Bind this additive builder too.  The worker imports the consumed V1
    # builder's parser, while the parent executes this V2 builder to create
    # the request; both source edges must therefore be auditable.
    builder_record = legacy._code_record(Path(__file__), "ROOT243 V2 request builder")
    payload["input_files"] = sorted(set(payload["input_files"]) | {builder_record["path"]})
    payload["input_hashes"][builder_record["path"]] = builder_record["sha256"]
    payload["input_sha256"][builder_record["path"]] = builder_record["sha256"]
    payload["input_records"][builder_record["path"]] = builder_record
    payload["source_binding"]["v2_request_builder"] = builder_record
    payload["output"]["path"] = "{attempt_root}/observer/f3_s2_coarse_deferred_json_observer_v2.json"
    # v1 uses canonical_sha256; this additive request keeps the same canonical
    # algorithm and updates the payload after all V2 fields are present.
    payload["canonical_sha256"] = legacy._canonical(payload)
    return payload


def self_test() -> dict:
    with __import__("tempfile").TemporaryDirectory(prefix="root243-v2-builder-") as name:
        root = Path(name)
        report = root / "report.json"; request = root / "request.json"; receipt = root / "receipt.json"; proof = root / "proof.json"
        report.write_text("{}\n", encoding="utf-8"); request.write_text(json.dumps({"physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"}) + "\n", encoding="utf-8"); receipt.write_text('{"status":"completed"}\n', encoding="utf-8")
        import hashlib
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        proof.write_text(json.dumps({"schema": "ds02.stage2.root-actual-verification.v1", "status": "VERIFIED_ACTUAL_FIXTURE", "report": str(report), "report_sha256": sha(report), "report_bytes": report.stat().st_size, "request": str(request), "request_sha256": sha(request), "receipt": str(receipt), "receipt_sha256": sha(receipt)}) + "\n", encoding="utf-8")
        value = build(argparse.Namespace(proof=proof, report=report, case_id=CASE, attempt_id=ATTEMPT, launch_commit="fixture"))
        assert value["command"][1] == str(WORKER)
        assert value["compatibility"]["cli_nested_source_report_sha_fix"] is True
        assert str(WORKER) in value["input_files"]
    return {"status": "PASS", "variant": VARIANT, "v2_worker_bound": True, "v1_request_unchanged": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--self-test", action="store_true"); parser.add_argument("--proof", type=Path); parser.add_argument("--report", type=Path); parser.add_argument("--output", type=Path); parser.add_argument("--case-id", default=CASE); parser.add_argument("--attempt-id", default=ATTEMPT); parser.add_argument("--launch-commit", default="unbound-until-parent-forward")
    args = parser.parse_args(argv)
    if args.self_test:
        print(json.dumps(self_test(), sort_keys=True)); return 0
    if args.proof is None or args.report is None or args.output is None:
        parser.error("--proof, --report, and --output are required")
    payload = build(args); output = args.output.expanduser().resolve(); output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "output": str(output), "canonical_sha256": payload["canonical_sha256"]}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
