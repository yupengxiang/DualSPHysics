from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f2_s1_trajectory_semantics_v1.py"
SPEC = importlib.util.spec_from_file_location("trajectory_semantics_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _binding(path: Path) -> dict[str, object]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest}


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    conversion = {
        "schema": "ds-data-02.bi4-direct-conversion.v1",
        "conversion_status": "completed",
        "typed_identity": {
            "initial_mass_min_kg": 0.0010000000474974513,
            "initial_mass_max_kg": 0.0010000000474974513,
            "blocks": [
                {"begin": 0, "count": 69405, "mk": 18, "tag": "fixed", "type": 0},
                {"begin": 69405, "count": 303435, "mk": 19, "tag": "fixed", "type": 0},
                {"begin": 372840, "count": 24150, "mk": 17, "tag": "moving", "type": 1},
                {"begin": 396990, "count": 7038, "mk": 1, "tag": "fluid", "type": 3},
                {"begin": 404028, "count": 7038, "mk": 2, "tag": "fluid", "type": 3},
                {"begin": 411066, "count": 7038, "mk": 3, "tag": "fluid", "type": 3},
            ],
        },
    }
    whole = 21114 * 0.0010000000474974513
    trajectory = {
        "schema": "ds02.stage2.f2-s1-trajectory-labels.v1",
        "status": "TRAJECTORY_LABELS_OBSERVED_OPEN_LIFECYCLE",
        "physical_case_id": MODULE.PHYSICAL_CASE,
        "trajectory": {"frames": 401, "identities": 418104, "time_window_s": [0.0, 4.000007783879406], "initial_fluid_mass_kg": whole},
        "mass_screen": {
            "initial_fluid_mass_kg": whole,
            "missing_identity_mass_kg": 0.002,
            "missing_identity_mass_fraction": 0.002 / whole,
            "unknown_final_destination_mass_kg": 0.003,
            "decision": "screening_only; no physical-fate or dynamics credit",
        },
        "unknown_scope": {
            "missing_identity": "open-lifecycle right censoring; physical fate and legal flux UNKNOWN",
            "dynamics": "UNKNOWN; no momentum/force/QN/QE inference",
        },
        "missing_identity_observations": {"semantics": "first saved-frame gap bracket only; physical event time, downstream region and fate UNKNOWN"},
        "events": [{
            "id": "receiver_entry",
            "axis": "x",
            "entry_direction": "+x",
            "operator_column_semantics": "column0=negative-to-positive along selected axis; column1=positive-to-negative",
            "entry_direction_mass_kg": 1.0,
            "exit_direction_mass_kg": 0.2,
            "entry_direction_net_flux_mass_kg": 0.8,
            "repeated_crossing_particles": 1,
            "semantics": "saved-frame finite-aperture bracket; hidden crossings unresolved",
        }],
    }
    records = []
    faces = [("x", -1.6001)] * 56 + [("z", -0.7001)] * 35 + [("y", -1.4001)] * 12 + [("z", 2.5001)] * 4 + [("y", 1.4001)] * 4
    for index, (axis, value) in enumerate(faces):
        point = [0.0, 0.0, 0.0]
        point["xyz".index(axis)] = value
        records.append({"idp": 100000 + index, "mk_absolute": index % 3 + 1, "motive": 1, "motive_name": "position", "position": point, "time_s": 0.5 + index * 0.01})
    particle_mass = 0.000625026375
    diagnostic_mass = 21.060888732
    expanded = {
        "case_id": "F2_S1_FINE_DOMAIN_EXPANDED_DP00855_XYZ_V1",
        "native_count": 111,
        "native_mass_lower_bound_kg": 111 * particle_mass,
        "native_mass_fraction_lower_bound": 111 * particle_mass / diagnostic_mass,
        "particle_mass_kg": particle_mass,
        "initial_mass_denominator_kg": diagnostic_mass,
        "records": records,
    }
    native = {
        "schema": "ds02.stage2.f2-s1-fine-expanded-native-weighted.v1",
        "status": "EXPANDED_NATIVE_WEIGHTED_RECONCILED",
        "physical_case_id": MODULE.PHYSICAL_CASE,
        "official_expanded_decoder": {"status": "completed", "returncode": 0, "h5_opened": False, "trajectory_opened": False},
        "paired_weighted_impact": {
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "expanded": expanded,
            "original": {"native_count": 175},
            "native_id_set_comparison": {"expanded_only_count": 62, "original_only_count": 126, "shared_count": 49},
        },
    }
    conversion_path = _write(tmp_path / "conversion.json", conversion)
    trajectory_path = _write(tmp_path / "trajectory.json", trajectory)
    native_path = _write(tmp_path / "native.json", native)
    runout_path = tmp_path / "Run.out"
    runout_path.write_text("MapRealPos(final)=(-1.6,-1.4,-0.7)-(3.2,1.4,2.5)\n", encoding="utf-8")
    contract = {
        "schema": MODULE.CONTRACT_SCHEMA,
        "physical_case_id": MODULE.PHYSICAL_CASE,
        "conversion_report": _binding(conversion_path),
        "trajectory_report": _binding(trajectory_path),
        "expanded_native_report": _binding(native_path),
        "expanded_runout": _binding(runout_path),
    }
    contract_path = _write(tmp_path / "contract.json", contract)
    return contract_path, {"trajectory": trajectory_path, "native": native_path}


def test_semantics_uses_typed_whole_mass_and_keeps_unknowns(tmp_path: Path) -> None:
    contract, _ = _fixture(tmp_path)
    result = MODULE.analyze(contract)
    assert result["whole_initial_mass_basis"]["fluid_count"] == 21114
    assert result["trajectory_saved_frame_labels"]["physical_fate"] == "UNKNOWN"
    assert result["expanded_xyz_native_visibility"]["strict_printed_boundary_faces"] == MODULE.EXPECTED_EXPANDED_FACE_COUNTS
    assert result["expanded_xyz_native_visibility"]["inside_count"] == 0
    assert result["comparison_limits"]["expanded_run_is_not_a_domain_only_causal_control"] is True


def test_wrong_trajectory_denominator_is_rejected(tmp_path: Path) -> None:
    contract, paths = _fixture(tmp_path)
    payload = json.loads(paths["trajectory"].read_text(encoding="utf-8"))
    payload["trajectory"]["initial_fluid_mass_kg"] = 21.060888732
    paths["trajectory"].write_text(json.dumps(payload) + "\n", encoding="utf-8")
    contract_payload = json.loads(contract.read_text(encoding="utf-8"))
    contract_payload["trajectory_report"] = _binding(paths["trajectory"])
    contract.write_text(json.dumps(contract_payload) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.SemanticError, match="trajectory whole initial mass"):
        MODULE.analyze(contract)


def test_multiple_printed_faces_are_rejected_as_ambiguous(tmp_path: Path) -> None:
    contract, paths = _fixture(tmp_path)
    payload = json.loads(paths["native"].read_text(encoding="utf-8"))
    payload["paired_weighted_impact"]["expanded"]["records"][0]["position"][1] = -1.4001
    paths["native"].write_text(json.dumps(payload) + "\n", encoding="utf-8")
    contract_payload = json.loads(contract.read_text(encoding="utf-8"))
    contract_payload["expanded_native_report"] = _binding(paths["native"])
    contract.write_text(json.dumps(contract_payload) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.SemanticError, match="face classification differs"):
        MODULE.analyze(contract)


def test_non_unknown_physical_claim_is_rejected(tmp_path: Path) -> None:
    contract, paths = _fixture(tmp_path)
    payload = json.loads(paths["native"].read_text(encoding="utf-8"))
    payload["paired_weighted_impact"]["physical_fate"] = "SPILL"
    paths["native"].write_text(json.dumps(payload) + "\n", encoding="utf-8")
    contract_payload = json.loads(contract.read_text(encoding="utf-8"))
    contract_payload["expanded_native_report"] = _binding(paths["native"])
    contract.write_text(json.dumps(contract_payload) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.SemanticError, match="grants physical or dynamical credit"):
        MODULE.analyze(contract)


def test_make_contract_binds_report_only_after_it_exists(tmp_path: Path) -> None:
    contract, paths = _fixture(tmp_path)
    original = json.loads(contract.read_text(encoding="utf-8"))
    output = tmp_path / "made-contract.json"
    result = MODULE.make_contract(
        paths["trajectory"],
        Path(original["conversion_report"]["path"]),
        paths["native"],
        Path(original["expanded_runout"]["path"]),
        output,
    )
    assert result["status"] == "CONTRACT_CREATED"
    assert MODULE.analyze(output)["status"] == "SEMANTICS_VALIDATED_SOURCE_BOUND"
