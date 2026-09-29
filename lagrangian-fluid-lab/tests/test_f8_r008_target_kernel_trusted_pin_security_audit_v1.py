from __future__ import annotations

import json
import inspect
from pathlib import Path

from scripts import f8_r008_target_kernel_readiness_projection_v1 as projection
from scripts import f8_r008_untrusted_pin_blocker_inventory_v1 as inventory

LAB = Path(__file__).parents[1]
REPORT_PATH = LAB / "reports/f8_r008_target_kernel_trusted_pin_security_audit_v1_report.json"


def test_security_audit_report_records_fail_closed_boundary_without_pins() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert report["status"] == "bounded_security_audit_completed_fail_closed"
    assert {finding["state"] for finding in report["findings"]} == {"fixed", "verified", "open"}
    assert report["target_runtime_evidence"] == {
        "real_external_attestation_present": False,
        "real_independent_trust_anchor_present": False,
        "real_runtime_measurement_present": False,
        "synthetic_target_or_runtime_pin_created_by_audit": False,
        "default_trusted_intake_status": "blocked_missing_external_trusted_pin_attestation",
        "blocker": "external target-kernel/source/config/build/runtime evidence is not supplied",
    }
    assert report["authorization_boundary"]["readiness_pass"] is False
    assert report["authorization_boundary"]["T1_numerical"] is False
    assert report["authorization_boundary"]["qualification_credit"] == 0
    assert all(item["state"] == "enforced" for item in report["cross_binding_matrix"])


def test_security_audit_report_preserves_f8_and_execution_boundaries() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert report["non_changes"] == [
        "F8 frozen registry",
        "T1 numerical result",
        "readiness gate",
        "qualification credit",
    ]
    assert all(value is False or value == 0 for value in report["side_effect_boundary"].values())
    assert report["prohibited_operations_not_performed"]
    assert {item["status"] for item in report["related_regression_blockers"]} == {
        "blocked",
        "blocked_at_collection",
    }


def test_untrusted_inventory_cannot_supply_readiness_inputs() -> None:
    inventory_report = inventory.verify_report()
    readiness_report = projection.build_projection()

    assert inventory_report["source_and_runtime_claims"]["promotion_surface"] == "none"
    assert inventory_report["authorization"]["readiness_pass"] is False
    assert inventory_report["authorization"]["qualification_credit"] == 0
    assert "untrusted_pin_blocker_inventory" not in inspect.getsource(projection.build_projection)
    assert readiness_report["authorization"]["readiness_pass"] is False
    assert readiness_report["authorization"]["qualification_credit"] == 0
