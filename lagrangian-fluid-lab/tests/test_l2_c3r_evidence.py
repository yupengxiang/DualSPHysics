from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from scripts import l2_c3r_evidence as c3r


def _write_runparts(path: Path, *, first_out: bool = True) -> None:
    rows = [
        "Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov",
        "0;0.0;0;0;0;0",
        "1;0.1;1;1;0;0" if first_out else "1;0.1;1;0;1;0",
    ]
    path.write_text("\n".join(rows) + "\n")


def _write_f5_fixture(tmp_path: Path, *, position_only: bool = True) -> dict[str, Path]:
    hdf5 = tmp_path / "f5.h5"
    valid = np.array([[True, True], [True, False], [True, False]], dtype=bool)
    position = np.zeros((3, 2, 3), dtype=np.float64)
    position[:, 0, 2] = [0.2, 0.4, 0.5]
    position[0, 1, 2] = 1.05
    position[1:, 1] = np.nan
    velocity = np.zeros_like(position)
    velocity[1:, 1] = np.nan
    mass = np.ones((3, 2), dtype=np.float64)
    mass[1:, 1] = np.nan
    with h5py.File(hdf5, "w") as handle:
        handle["time"] = np.array([0.0, 0.1, 0.2])
        handle["valid"] = valid
        handle["particle_id"] = np.array([10, 11], dtype=np.int64)
        handle["position"] = position
        handle["velocity"] = velocity
        handle["mass"] = mass

    attempt = tmp_path / "attempt"
    attempt.mkdir()
    (attempt / "attempt.json").write_text(json.dumps({
        "attempt_id": "fixture-attempt",
        "status": "completed",
        "returncode": 0,
    }))
    _write_runparts(attempt / "RunPARTs.csv", first_out=position_only)
    (attempt / "Run.out").write_text(
        "MapRealPos(final)=(-0.1,-0.1,-0.1)-(1.1,1.1,1.05162)\n"
        "TimeMax=0.2\n"
        "Finished execution (code=0)\n"
        "Excluded particles...............: 1\n"
    )
    (attempt / "process.stdout.log").write_text("Finished execution (code=0)\n")
    definition = tmp_path / "definition.xml"
    definition.write_text("<case><simulationdomain><posmax z='default + 75%' /></simulationdomain></case>")
    generated = tmp_path / "generated.xml"
    generated.write_text(
        "<case><simulationdomain><posmax z='default + 75%' /></simulationdomain>"
        "<particles><_summary><positions><posmax z='0.6' /></positions></_summary></particles>"
        "<drawbox><boxfill>bottom | left | right | front | back</boxfill></drawbox></case>"
    )
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({
        "baseline_commit": "legacy-commit",
        "attempts": [{
            "family": "F5",
            "attempt": {"attempt_id": "fixture-attempt", "status": "completed", "returncode": 0},
            "definition_sha256": c3r.sha256_file(definition)[0],
            "generated_xml_sha256": c3r.sha256_file(generated)[0],
        }],
        "audits": [{
            "family": "F5",
            "hdf5_sha256": c3r.sha256_file(hdf5)[0],
            "canary_hard_integrity_pass": False,
            "independent_audit": {"errors": ["nonfinite:position"]},
        }],
    }))
    return {
        "hdf5": hdf5,
        "attempt": attempt,
        "definition": definition,
        "generated": generated,
        "legacy": legacy,
    }


def _f6_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "r3-g2-f6-mdbc-preflight.json"
    path.write_text(json.dumps({
        "acceptance_status": "diagnostic_only_not_physical_acceptance",
        "mdbc_claim": "not_accepted_mdbc_preflight",
        "normal_completeness": {
            "complete_for_all_boundary_particles": False,
            "gencase_boundary_count": 24335,
            "gencase_zero_count": 792,
            "solver_fixed_or_moving_zero_count": 792,
        },
        "gencase": {"normal_data": {"zero_count": 792}},
        "solver": {"normal_data": {
            "fixed_or_moving_zero_count": 792,
            "solver_finished_code_0": True,
            "chrono_collision_warning": True,
        }},
        "definition": {"xml_switch": {"current_f6": {
            "requested_boundary": {"value": 1, "name": "DBC"},
            "geometry_commands": {"normals_list_present": False},
            "normals": {"section_present": False},
        }}},
    }))
    return path


def test_parse_runparts_separates_position_exclusion_from_density_loss(tmp_path: Path):
    path = tmp_path / "RunPARTs.csv"
    _write_runparts(path)

    parsed = c3r.parse_runparts(path)

    assert parsed["totals"] == {"np_out": 1, "np_out_pos": 1, "np_out_rho": 0, "np_out_mov": 0}
    assert parsed["first_out"]["np_out_pos"]["time_s"] == 0.1
    assert parsed["first_out"]["np_out_rho"] is None


def test_f5_root_cause_reconciles_historical_identity_loss_without_promoting_it(tmp_path: Path):
    fixture = _write_f5_fixture(tmp_path)

    report = c3r.audit_f5_loss_root_cause(
        legacy_report_path=fixture["legacy"],
        hdf5_path=fixture["hdf5"],
        attempt_dir=fixture["attempt"],
        definition_path=fixture["definition"],
        generated_xml_path=fixture["generated"],
    )

    assert report["status"] == "confirmed"
    assert report["root_cause_id"] == "F5_RUNTIME_DOMAIN_POSITION_EXCLUSION"
    assert report["trajectory"]["loss_identity_summary"]["missing_initial_identity_count"] == 1
    assert report["solver_output"]["runparts"]["totals"]["np_out_pos"] == 1
    assert report["execution_origin"] == "legacy_artifact_reaudit"
    assert report["new_solver_execution"] is False
    assert report["repair_required"]["new_execution_needed"] is True


def test_f5_non_position_out_is_not_called_a_confirmed_domain_root_cause(tmp_path: Path):
    fixture = _write_f5_fixture(tmp_path, position_only=False)

    report = c3r.audit_f5_loss_root_cause(
        legacy_report_path=fixture["legacy"],
        hdf5_path=fixture["hdf5"],
        attempt_dir=fixture["attempt"],
        definition_path=fixture["definition"],
        generated_xml_path=fixture["generated"],
    )

    assert report["status"] == "inconclusive"
    assert report["root_cause_id"] is None
    assert report["causal_checks"]["partout_is_position_only"] is False


def test_f6_blocker_requires_structured_normal_chrono_and_force_gauge_evidence(tmp_path: Path):
    preflight = _f6_fixture(tmp_path)
    static = tmp_path / "r3-g2-f6-static-buoyancy.json"
    static.write_text(json.dumps({
        "acceptance_status": "diagnostic_only_not_physical_acceptance",
        "hypotheses": [{"evidence": {"mdbc_normals_verified_for_f6": False}}],
    }))
    wall = tmp_path / "r3-f6-wall-ghost-geometry.json"
    wall.write_text(json.dumps({
        "acceptance_status": "candidate_geometry_only_rejected",
        "open_blockers": ["Create a fixed-body force gauge and matched DBC/mDBC hydrostatic run after E0 passes."],
    }))
    test14 = tmp_path / "r3-g2-f6-test14.json"
    test14.write_text(json.dumps({"execution_status": "completed", "scientific_acceptance": "rejected"}))

    report = c3r.audit_f6_external_blocker([preflight, static, wall, test14])

    assert report["status"] == "blocked_external"
    assert report["blocker_id"] == "F6_MDBC_NORMALS_CHRONO_FORCE_GAUGE_CONTRACT"
    assert report["observed"]["normal_completeness"]["zero_count"] == 792
    assert report["observed"]["chrono_collision_warning"] is True
    assert report["new_solver_execution"] is False


def test_build_report_separates_f5_finding_and_f6_blocker(tmp_path: Path):
    fixture = _write_f5_fixture(tmp_path)
    preflight = _f6_fixture(tmp_path)
    static = tmp_path / "r3-g2-f6-static-buoyancy.json"
    static.write_text(json.dumps({"hypotheses": [{"evidence": {"mdbc_normals_verified_for_f6": False}}]}))
    wall = tmp_path / "r3-f6-wall-ghost-geometry.json"
    wall.write_text(json.dumps({
        "acceptance_status": "candidate_geometry_only_rejected",
        "open_blockers": ["fixed-body force gauge required"],
    }))
    test14 = tmp_path / "r3-g2-f6-test14.json"
    test14.write_text(json.dumps({"execution_status": "completed"}))

    report = c3r.build_report(
        legacy_report_path=fixture["legacy"],
        hdf5_path=fixture["hdf5"],
        attempt_dir=fixture["attempt"],
        definition_path=fixture["definition"],
        generated_xml_path=fixture["generated"],
        f6_report_paths=[preflight, static, wall, test14],
    )

    assert report["schema"] == "l2.c3r.evidence.v1"
    assert report["status"] == "complete_with_findings"
    assert report["execution_policy"]["new_solver_execution"] is False
    assert report["execution_policy"]["resume_or_closeout_modified"] is False
    assert report["qualification_claim"] == "none; C3R evidence and blocker only"
