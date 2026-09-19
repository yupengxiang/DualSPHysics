"""Contract tests for the independent L2-R F6 blocker audit."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts import l2_f6r_blocker_audit as audit


def _write_force_csv(path: Path, values: list[tuple[float, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["time [s]", "force [N]", "forcex [N]", "forcey [N]", "forcez [N]"])
        for time_s, force_z in values:
            writer.writerow([time_s, abs(force_z), 0.0, 0.0, force_z])


def _force_case(case_id: str, csv_path: str, *, normal_zero: int = 0, stable: bool = True) -> dict:
    return {
        "case_id": case_id,
        "run_label": case_id,
        "acceptance_status": "candidate_not_accepted",
        "force_gauge": {
            "signed_csv": csv_path,
            "header": ["time [s]", "force [N]", "forcex [N]", "forcey [N]", "forcez [N]"],
        },
        "fixed_body_mapping_gate": {
            "source_mkbound_maps_to_fixed": "dbc" in case_id,
            "source_mkbound_maps_to_one_fixed_row": "mdbc" in case_id,
            "no_floatings": True,
            "no_moving_or_floating_rows": True,
        },
        "normal_ghost_audit": {
            "normal_zero_count": normal_zero,
            "gate": normal_zero == 0,
            "checks": {"no_zero_normals": normal_zero == 0},
        },
        "screen": {"stable_window_gate": stable},
    }


def test_default_contract_preserves_the_external_f6_blocker():
    report = audit.build_contract()

    assert report["schema"] == "l2.f6r.blocker_contract.v1"
    assert report["status"] == "complete_with_findings"
    assert report["decision"] == "blocked_external"
    assert report["blocker_id"] == "F6_MDBC_NORMALS_CHRONO_FORCE_GAUGE_CONTRACT"
    assert report["audit_policy"]["new_solver_execution"] is False
    assert report["audit_policy"]["resume_modified"] is False

    normals = report["observed"]["normal_contract"]
    assert normals["f6_target"]["zero_count"] == 792
    assert normals["f6_target"]["fixed_or_moving_zero_count"] == 792
    assert normals["gate"] is False

    chrono = report["observed"]["chrono_contract"]
    assert chrono["warning"]["recorded_by_solver_evidence"] is True
    assert chrono["gate"] is False

    force = report["observed"]["force_gauge_contract"]
    assert force["fixed_box_control"]["dbc"]["present"] is True
    assert force["fixed_box_control"]["mdbc"]
    assert force["f6_target"]["present"] is False
    assert force["gate"] is False


def test_force_gauge_audit_keeps_a_fixed_box_pair_diagnostic(tmp_path: Path):
    case_root = tmp_path / "case"
    dbc_trace = case_root / "dbc.csv"
    mdbc_trace = case_root / "mdbc.csv"
    _write_force_csv(dbc_trace, [(0.0, 78.48), (0.1, 78.48), (0.2, 78.48)])
    _write_force_csv(mdbc_trace, [(0.0, 78.48), (0.1, 78.48), (0.2, 78.48)])
    dbc_report = {
        "analytical_reference": {"fz_n": 78.48},
        "source_semantics": {"force": "fixed pressure"},
        "cases": [_force_case("fixed_box_dbc_gravity", "dbc.csv")],
    }
    mdbc_report = {
        "analytical_reference": {"fz_n": 78.48},
        "source_semantics": {"force": "fixed pressure"},
        "cases": [_force_case("fixed_box_mdbc_canonical", "mdbc.csv")],
    }

    result = audit.audit_force_gauge_comparison(
        dbc_report=dbc_report,
        dbc_report_path=case_root / "dbc-report.json",
        mdbc_report=mdbc_report,
        mdbc_report_path=case_root / "mdbc-report.json",
        f6_reports=[{"family": "F6", "case_id": "F6_float1"}],
    )

    assert result["fixed_box_control"]["pair_reference_match"] is True
    assert result["fixed_box_control"]["dbc"]["last_0p20s"]["forcez_mean_n"] == 78.48
    assert result["f6_target"]["present"] is False
    assert result["gate"] is False


def test_force_gauge_gate_rejects_zero_normals_and_unstable_trace(tmp_path: Path):
    case_root = tmp_path / "case"
    _write_force_csv(case_root / "dbc.csv", [(0.0, 78.48), (0.1, 78.48), (0.2, 78.48)])
    _write_force_csv(case_root / "mdbc.csv", [(0.0, 60.0), (0.1, 100.0), (0.2, 60.0)])
    dbc_report = {
        "analytical_reference": {"fz_n": 78.48},
        "source_semantics": {"force": "fixed pressure"},
        "cases": [_force_case("fixed_box_dbc_gravity", "dbc.csv")],
    }
    mdbc_report = {
        "analytical_reference": {"fz_n": 78.48},
        "source_semantics": {"force": "fixed pressure"},
        "cases": [_force_case("fixed_box_mdbc_canonical", "mdbc.csv", normal_zero=3, stable=False)],
    }

    result = audit.audit_force_gauge_comparison(
        dbc_report=dbc_report,
        dbc_report_path=case_root / "dbc-report.json",
        mdbc_report=mdbc_report,
        mdbc_report_path=case_root / "mdbc-report.json",
        f6_reports=[],
    )

    assert result["checks"]["mdbc_control_zero_normal_gate"] is False
    assert result["checks"]["mdbc_control_stable_force_gate"] is False
    assert result["gate"] is False


def test_parse_definition_distinguishes_floating_chrono_path_from_fixed_body(tmp_path: Path):
    floating = tmp_path / "floating.xml"
    floating.write_text(
        "<case><casedef><floatings><floating mkbound='7'/></floatings>"
        "</casedef><execution><parameters>"
        "<parameter key='Boundary' value='2'/><parameter key='RigidAlgorithm' value='1'/>"
        "</parameters></execution></case>"
    )
    fixed = tmp_path / "fixed.xml"
    fixed.write_text(
        "<case><casedef><geometry><commands><force name='BodyForce'>"
        "<target mkbound='1'/></force></commands></geometry></casedef>"
        "<execution><parameters><parameter key='Boundary' value='2'/></parameters></execution></case>"
    )

    floating_audit = audit.parse_definition(floating)
    fixed_audit = audit.parse_definition(fixed)

    assert floating_audit["has_floatings_container"] is True
    assert floating_audit["floating_count"] == 1
    assert floating_audit["rigid_algorithm"] == 1
    assert fixed_audit["has_floatings_container"] is False
    assert fixed_audit["force_gauges"] == [{"name": "BodyForce", "mkbound": "1"}]


def test_contract_has_explicit_unblock_and_non_claim_conditions():
    report = audit.build_contract()
    assert report["required_to_unblock"]
    assert any("Chrono" in item for item in report["required_to_unblock"])
    assert any("radius-offset" in item for item in report["do_not_claim"])
    assert all(item["release_conditions"] for item in report["blockers"])
