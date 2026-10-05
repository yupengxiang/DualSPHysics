#!/usr/bin/env python3
"""Validate fresh107 JSON/source bindings without runtime or scientific-payload reads."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def is_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def main() -> int:
    manifest = load(HERE / "F2_STAGE1_FRESH107_ACTUAL_NATIVE_TYPED_SCOPE_BIND_MANIFEST.json")
    source_validation = load(HERE / "evidence/fresh107-source-validation.json")
    csv_evidence = load(HERE / "evidence/csv-reuse-closure.json")
    failures: list[str] = []
    rows = manifest.get("cases", [])
    if manifest.get("case_count") != 16 or len(rows) != 16:
        failures.append("case_count")
    if source_validation.get("status") != "pass":
        failures.append("builder_source_validation")
    if csv_evidence.get("all_csv_closures_pass") is not True:
        failures.append("csv_evidence")

    for row in rows:
        cid = row.get("case_id", "<missing>")
        typed_binding = row.get("typed_request") or {}
        csv_binding = row.get("csv_reuse_request") or {}
        try:
            typed = load(Path(typed_binding["path"]))
            csv_req = load(Path(csv_binding["path"]))
        except Exception as exc:
            failures.append(f"load:{cid}:{type(exc).__name__}")
            continue

        if typed.get("disabled") is not True or typed.get("execution_allowed") is not False or typed.get("launch_allowed") is not False:
            failures.append(f"typed-disabled:{cid}")
        if typed.get("typed_receipt_sha256") is not None or typed.get("conversion_report_sha256") is not None or typed.get("trajectory_h5_sha256") is not None:
            failures.append(f"future-typed-hash:{cid}")
        if row.get("typed_command_closure", {}).get("passed") is not True:
            failures.append(f"typed-closure:{cid}")
        if row.get("actual_native_status") != "completed/0":
            failures.append(f"native-status:{cid}")
        gate = typed.get("actual_native_gate") or {}
        if gate.get("native_receipt_completed0") is not True or gate.get("recipe_matches") is not True:
            failures.append(f"native-gate:{cid}")
        if typed.get("expected_dimension") != 3 or typed.get("expected_native_frames") != 401:
            failures.append(f"recipe-shape:{cid}")
        if typed.get("prepared_particle_counts") != {"fixed": 372840, "moving": 24150, "fluid": 21114, "floating": 0}:
            failures.append(f"counts:{cid}")
        if typed.get("canonical_grant") is not False or typed.get("actual_converter_physical_condition_sha256") is not None:
            failures.append(f"scope-grant:{cid}")
        if typed.get("producer_scope_schema") != "legacy-owner-scope.v0":
            failures.append(f"scope-schema:{cid}")
        if typed.get("root230_dispatch", {}).get("source_agent_must_not_resolve") is not True:
            failures.append(f"root230-ownership:{cid}")
        if typed.get("no_arrays_read") is not True or typed.get("no_jobs_started") is not True:
            failures.append(f"source-only:{cid}")

        if csv_req.get("disabled") is not True or csv_req.get("execution_allowed") is not False or csv_req.get("launch_allowed") is not False:
            failures.append(f"csv-disabled:{cid}")
        if csv_req.get("no_partvtk_rerun_required") is not True or csv_req.get("raw_csv_not_read_or_hashed_here") is not True:
            failures.append(f"csv-source-only:{cid}")
        csv = csv_req.get("registered_csv") or {}
        if not isinstance(csv.get("path"), str) or not is_digest(csv.get("sha256")):
            failures.append(f"csv-producer-binding:{cid}")
        closure = csv_req.get("command_input_closure") or {}
        if closure.get("passed") is not True or closure.get("actual_report_csv_producer_record_present") is not True:
            failures.append(f"csv-closure:{cid}")
        if closure.get("upstream_root416_partvtk_gap_preserved") is not True:
            failures.append(f"root416-gap-disclosure:{cid}")

    result = {
        "schema": "ds02.f2.stage1.fresh107.source-contract-validation.v1",
        "case_count": len(rows),
        "actual_native_completed0_count": sum(x.get("actual_native_status") == "completed/0" for x in rows),
        "typed_requests_disabled": not any(x.startswith("typed-disabled:") for x in failures),
        "typed_command_closures_pass": not any(x.startswith("typed-closure:") for x in failures),
        "csv_reuse_closures_pass": not any(x.startswith("csv-closure:") for x in failures),
        "root416_partvtk_gap_disclosed": not any(x.startswith("root416-gap-disclosure:") for x in failures),
        "typed_completed0_count": 0,
        "future_h5_hashes_null": not any(x.startswith("future-typed-hash:") for x in failures),
        "actual_converter_scope_sha256_claimed": 0,
        "canonical_grant": False,
        "native_restarted": False,
        "runtime_v2_validate_request_called": False,
        "scientific_payloads_read_or_hashed_here": [],
        "failures": failures,
        "status": "pass" if not failures else "fail",
    }
    out = HERE / "evidence/fresh107-validator-run.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
