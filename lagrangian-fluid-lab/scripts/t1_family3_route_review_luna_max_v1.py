#!/usr/bin/env python3
"""Read-only bounded audit for the third-Core-T1 family search.

This checker binds the existing F1/F2/F5/F6 route-closure receipts and the
latest F2 submerged-orifice v4 hard failure.  It deliberately does not open
large trajectory fields and has no Definition writer, case-generation executable,
solver, GPU, queue, registry, ledger, matrix, or denominator mutation path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
AUDIT = LAB / (
    "campaigns/core-v1/cfd/t1-family3-route-review-luna-max-v1/route-audit-v1.json"
)
NAMESPACE = AUDIT.parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def local(relative: str) -> Path:
    path = LAB / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def check() -> dict[str, Any]:
    audit = load(AUDIT)
    assert audit["schema"] == "core.t1_family3.route_review.route_closed_negative.v1"
    assert audit["status"] == "route_closed_negative_no_new_hypothesis"
    assert audit["decision"] == "close_bounded_f1_f2_f5_f6_search_without_new_candidate"
    assert audit["qualification_credit_added"] == 0
    assert audit["protected_state_mutation"] == {
        "registry": 0,
        "ledger": 0,
        "matrix": 0,
        "denominator": 0,
        "queue": 0,
        "solver_invoked": False,
        "gpu_started": False,
    }

    completion = load(local("campaigns/core-v1/completion.json"))
    assert completion["t1_families"] == ["F3", "F4"]
    assert completion["checks"]["three_t1_families"] is False
    assert completion["missing_t1_case_runs"] == 288

    f1_f2 = load(local("campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v2.json"))
    f5 = load(
        local(
            "campaigns/core-v1/evidence/"
            "f5-wave-runup-third-t1-route-closed-no-new-hypothesis-v1.json"
        )
    )
    f6 = load(
        local("campaigns/core-v1/cfd/f6-observation-axis-v4-third-t1-route-closed-v1.json")
    )
    f1_f2_receipt = load(
        local("campaigns/core-v1/evidence/f1-f2-third-t1-route-decision-receipt-v2.json")
    )
    f6_receipt = load(
        local("campaigns/core-v1/evidence/f6-observation-axis-v4-third-t1-route-decision-receipt-v1.json")
    )
    f2_v4 = load(
        local(
            "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
            "normal-remediation-v4/preflight-v4/preflight.json"
        )
    )
    f2_partition = load(
        local(
            "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/"
            "normal-remediation-v4/v4-current-failure-partition-audit-v1.json"
        )
    )

    assert f1_f2["status"] == "route_closed_no_new_hypothesis"
    assert f5["status"] == "f5_route_closed_no_new_hypothesis"
    assert f6["status"] == "route_closed_no_new_hypothesis"
    assert f1_f2_receipt["route_decision"]["new_physical_definition_found"] is False
    assert f6_receipt["route_decision"]["new_physical_definition_found"] is False
    assert f5["fixed_denominator"]["denominator_mutation"] == 0
    assert f5["execution_controls"]["solver_invoked"] is False

    assert f2_v4["case_id"] == "F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v4"
    assert f2_v4["preflight_pass"] is False
    assert f2_v4["native_initial"]["zero_boundnor_count"] == 29484
    assert f2_v4["native_initial"]["zero_normal_size_count"] == 29484
    assert f2_v4["native_initial"]["ids_match_generated_xml"] is True
    assert f2_v4["native_initial"]["arrays_finite"] is True
    assert f2_v4["native_initial"]["wall_endpoint_outer_count"] == 0
    assert f2_v4["native_initial"]["zero_boundnor_count"] > 0
    assert f2_v4["mass_contract"]["pass"] is True
    assert f2_v4["mass_contract"]["relative_error"] == 0.007812500000000222
    assert f2_v4["solver_product_present"] is False
    assert f2_v4["matrix_credit"] == 0
    assert f2_v4["execution_controls"]["solver_invoked"] is False
    assert f2_v4["execution_controls"]["gpu_invoked"] is False
    assert f2_partition["status"] == "read_only_v4_failure_partition_closed"
    assert f2_partition["global"]["zero_boundnor_count"] == 29484
    assert f2_partition["global"]["zero_normal_size_count"] == 29484
    partitions = {row["mk"]: row for row in f2_partition["mk_partitions"]}
    assert partitions[17]["zero_boundnor_count"] == 0
    assert partitions[18]["zero_boundnor_count"] == 29484
    assert f2_partition["interpretation"]["hard_gate_preserved"] is True
    assert f2_partition["interpretation"]["same_input_retry"] is False
    assert f2_partition["interpretation"]["no_route_authorization"] is True

    screen = audit["candidate_screen"]
    assert screen["status"] == "screened_not_admitted_insufficient_evidence"
    assert screen["root_review_ready"] is False
    assert screen["runtime_authorized"] is False
    assert screen["not_written"] == [
        "no candidate card",
        "no new Definition",
        "no static preflight contract",
    ]

    forbidden_new_candidate_names = (
        "candidate-card-v1.json",
        "static-preflight-contract-v1.json",
        "F2_ORIFICE_q0p50_dp0075_native_dbc_boundary_hypothesis_v1_Def.xml",
    )
    for name in forbidden_new_candidate_names:
        assert not any(NAMESPACE.rglob(name)), f"unexpected unadmitted artifact: {name}"

    for binding in audit["source_receipts"]:
        path = local(binding["path"])
        assert sha256(path) == binding["sha256"], f"stale hash: {binding['path']}"

    return {
        "status": audit["status"],
        "f2_v4_zero_boundnor": f2_v4["native_initial"]["zero_boundnor_count"],
        "f2_v4_gate_mk18_zero_boundnor": partitions[18]["zero_boundnor_count"],
        "f2_v4_outer_mk17_zero_boundnor": partitions[17]["zero_boundnor_count"],
        "candidate_screen_status": screen["status"],
        "root_review_ready": screen["root_review_ready"],
        "qualification_credit": audit["qualification_credit_added"],
        "protected_mutations": audit["protected_state_mutation"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="run the read-only audit")
    args = parser.parse_args()
    if not args.check:
        parser.error("only --check is available; this script never writes or executes")
    print(json.dumps(check(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
