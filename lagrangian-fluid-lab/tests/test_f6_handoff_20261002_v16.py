from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_f6_handoff_20261002_v16.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_handoff_20261002_v16", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
F6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F6)


def test_domain_xy_repair_all_six_native_contracts_are_actual_and_strict() -> None:
    audit = F6.read_json(F6.AUDIT_PATH)
    assert audit["status"] == "all_six_native_preflight_pass"
    assert len(audit["cases"]) == 6
    expected_faces = {
        "coarse": {"x_min": 961, "x_max": 961, "y_min": 1891, "y_max": 1891, "z_min": 1891},
        "medium": {"x_min": 2401, "x_max": 2401, "y_min": 4753, "y_max": 4753, "z_min": 4753},
        "fine": {"x_min": 3721, "x_max": 3721, "y_min": 7381, "y_max": 7381, "z_min": 7381},
    }
    expected_masspart = {"coarse": 0.512, "medium": 0.125, "fine": 0.064}
    for row in audit["cases"]:
        contract = row["generated_native_contract"]
        ledger = contract["native_initial_mass_ledger"]
        faces = row["native_boundary_vtk"]["fixed_face_coverage"]["counts"]
        assert contract["solver_dimension"] == 3
        assert ledger["fluid_mass_kg"] == 5120.0
        assert contract["floating_contract"]["massbody_kg"] == 128.0
        assert contract["floating_contract"]["masspart_kg"] == expected_masspart[row["resolution_id"]]
        assert contract["floating_contract"]["center_m"] == [2.4, 1.2, 1.08]
        assert contract["floating_contract"]["inertia_diag_kg_m2"] == [8.53333, 8.53333, 13.6533]
        assert faces == expected_faces[row["resolution_id"]]
        assert row["preflight_pass"] is True
        assert row["repair_scope"]["same_root_cause_repair_count"] == 2


def test_medium_terminal_audit_preserves_one_simple_exclusion_as_negative_evidence() -> None:
    audit = F6.read_json(F6.MEDIUM_AUDIT_PATH)
    rows = {row["mechanism_id"]: row for row in audit["cases"]}
    assert audit["status"] == "both_solver_terminal_reviewed"
    assert rows["simple_free_response"]["runparts"]["numeric_rows"] == 241
    assert rows["simple_free_response"]["runparts"]["cumulative_exclusions"] == {
        "NpOut": 1,
        "NpOutPos": 1,
        "NpOutRho": 0,
        "NpOutMov": 0,
    }
    assert "negative evidence" in rows["simple_free_response"]["simple_exclusion_note"]
    assert rows["wave_no_contact"]["runparts"]["numeric_rows"] == 241
    assert rows["wave_no_contact"]["runparts"]["cumulative_exclusions"] == {
        "NpOut": 0,
        "NpOutPos": 0,
        "NpOutRho": 0,
        "NpOutMov": 0,
    }
    assert all(row["postprocessing_ready"] for row in rows.values())


def test_four_gpu_requests_are_root_only_and_all_inputs_exist() -> None:
    root = F6.REQUEST_ROOT
    requests = [F6.read_json(path) for path in sorted(root.glob("*.json")) if path.name != "request_manifest.json"]
    assert len(requests) == 4
    assert {(row["mechanism_id"], row["resolution_id"]) for row in requests} == {
        ("simple_free_response", "coarse"),
        ("simple_free_response", "fine"),
        ("wave_no_contact", "coarse"),
        ("wave_no_contact", "fine"),
    }
    for request in requests:
        assert request["kind"] == "qualification"
        assert "root only" in request["launch_authority"]
        assert request["command"][0].endswith("DualSPHysics5.4_linux64")
        assert request["command"][2] == "{attempt_root}/solver_output"
        assert all(Path(path).is_file() for path in request["input_files"])
        assert request["qualification_claim"].startswith("none")


def test_postprocessing_requests_bind_old_raw_tree_and_defer_h5_labels() -> None:
    root = F6.POST_REQUEST_ROOT
    requests = [F6.read_json(path) for path in sorted(root.glob("*.json"))]
    assert len(requests) == 8
    assert {request["cpu_task_kind"] for request in requests} == {"audit", "conversion", "labels"}
    for request in requests:
        assert request["q_n_status"] == "pending"
        if request["cpu_task_kind"] == "labels":
            assert request["deferred_until_attempt"].endswith("_NATIVE_H5_001")
            assert request["source_trajectory_sha256"] == "deferred_until_native_h5_receipt"
            missing = [path for path in request["input_files"] if not Path(path).is_file()]
            assert len(missing) == 1
            assert missing[0].endswith("trajectory.h5")
        else:
            assert all(Path(path).is_file() for path in request["input_files"])
        if request["cpu_task_kind"] == "audit" and "computeforces" in request["attempt_id"].lower():
            assert "--generated-xml" in request["command"]
