from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
F2 = LAB / "campaigns/ds-data-02/families/F2"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POST = _load("f2_postsolver_20261002", F2 / "f2_handoff_20261002_postsolver.py")
LEDGER = _load("f2_native_ledger_20261002", F2 / "f2_handoff_20261002_native_ledger.py")
NUMERIC = _load("f2_numeric_studies_20261002", F2 / "f2_handoff_20261002_numeric_studies.py")
NUMERIC_V3 = _load("f2_numeric_studies_20261002_v3", F2 / "f2_handoff_20261002_numeric_studies_v3.py")
DOMAIN = _load("f2_exclusion_domain_diagnostic_20261002", F2 / "f2_handoff_20261002_exclusion_domain_diagnostic.py")


def test_postsolver_uses_frame_partvtk_and_keeps_ledger_as_a_separate_stage():
    assert POST.PARTVTK.name == "PartVTK_linux64"
    source = (F2 / "f2_handoff_20261002_postsolver.py").read_text(encoding="utf-8")
    assert "materialize_native_ledger" in source
    assert "native exclusion/lifecycle audit" in source
    assert "no Q-I/Q-N/production claim" in source


def test_owner_metadata_freezes_continuum_geometry_and_three_source_layers():
    path = F2 / "handoff_20261002/postsolver/owner_metadata/F2H10V2_CENTER_V1_MEDIUM.generator.v2.metadata.json"
    owner = json.loads(path.read_text(encoding="utf-8"))
    binding = owner["physical_binding"]
    assert owner["solver_dimension"] == 3
    assert binding["geometry"]["fluid"]["size_m"] == [0.32, 0.24, 0.32]
    assert len(binding["initial_state"]["source_regions"]) == 3
    assert binding["initial_state"]["mass_policy"].startswith("native BI4 header")
    assert owner["qualification_claim"] == "none"
    assert owner["production_claim"] == "none"


def test_runparts_parser_sums_per_save_increments_instead_of_using_last_row(tmp_path):
    path = tmp_path / "RunPARTs.csv"
    fields = ["Part", "TimeStep [s]", "NpOut", "NpOutPos", "NpOutRho", "NpOutMov", "NpNew", "NpSim", "NpfSim", "NpNormal"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerow({key: "0" for key in fields})
        writer.writerow({**{key: "0" for key in fields}, "Part": "1", "NpOut": "2", "NpOutPos": "2", "NpSim": "10", "NpfSim": "3", "NpNormal": "10", "TimeStep [s]": "0.1"})
        writer.writerow({**{key: "0" for key in fields}, "Part": "2", "NpOut": "3", "NpOutPos": "3", "NpSim": "10", "NpfSim": "3", "NpNormal": "10", "TimeStep [s]": "0.2"})
    report = LEDGER.parse_runparts(path)
    assert report["counters"]["NpOut"]["sum"] == 5.0
    assert report["counters"]["NpOutPos"]["sum"] == 5.0
    assert report["counters"]["NpOut"]["nonzero_rows"] == 2


def test_native_ledger_mode_keeps_physical_spill_separate_from_partout_unknown():
    source = (F2 / "f2_handoff_20261002_native_ledger.py").read_text(encoding="utf-8")
    assert LEDGER.MODE == "finite_initial_numerical_cohort_with_exclusions"
    assert "PartVTKOut exclusion is never spill" in source
    assert "physical_spill_classification" in source


def test_numeric_studies_are_four_second_prepared_comparisons_with_real_dt_control():
    plan_path = F2 / "handoff_20261002/numerical_studies_v2/numeric-study-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["event_window_s"] == 4.0
    assert plan["physical_geometry_unchanged"] is True
    assert plan["mass_rescaling"] is False
    assert plan["common_half_dt_fixed_s"] == 3.695219335558999e-05
    assert len(plan["studies"]) == 4
    assert {row["study"] for row in plan["studies"]} == {"half_dt", "half_save"}
    for row in plan["studies"]:
        request = json.loads(Path(row["request"]).read_text(encoding="utf-8"))
        assert request["qualification_claim"] == "none"
        assert request["event_window_s"] == 4.0
        if row["study"] == "half_dt":
            assert request["numerical_study"]["dt_fixed_s"] == plan["common_half_dt_fixed_s"]
            assert request["numerical_study"]["time_out_s"] == 0.01
        else:
            assert request["numerical_study"]["dt_fixed_s"] == 0.0
            assert request["numerical_study"]["time_out_s"] == 0.005
        assert all(Path(path).is_file() for path in request["input_files"])


def test_numeric_xml_parameter_replacement_requires_exactly_one_parameter(tmp_path):
    source = '<parameter key="DtFixed" value="0" />\n'
    assert 'value="1.25e-4"' in NUMERIC.replace_parameter(source, "DtFixed", "1.25e-4")


def test_numeric_studies_v3_binds_each_background_receipt_and_freezes_physical_inputs():
    plan_path = F2 / "handoff_20261002/numerical_studies_v3/numeric-study-plan-v3.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["study_version"] == "v3_correct_background_receipts_and_physical_equality"
    assert plan["event_window_s"] == 4.0
    assert len(plan["studies"]) == 4
    for row in plan["studies"]:
        request = json.loads(Path(row["request"]).read_text(encoding="utf-8"))
        case_id = row["case_id"]
        receipt_path = Path(row["solver_receipt"]["path"])
        assert case_id in receipt_path.parts
        assert request["gencase_artifacts"]["solver_receipt"]["path"] == str(receipt_path)
        equality = request["physical_input_equality"]
        assert equality["xml_allowed_control_changes"] == ["DtFixed", "TimeOut"]
        assert equality["xml_normalized_equal"] is True
        assert equality["bi4_hash_equal"] is True
        assert equality["motion_hash_equal"] is True
        assert request["numerical_study"]["xml_dtini"] == "0"
        assert request["numerical_study"]["xml_dtmin"] == "0"
        assert all(Path(path).is_file() for path in request["input_files"])


def test_exclusion_domain_diagnostic_keeps_domain_evidence_separate_from_spill(tmp_path):
    xml = tmp_path / "case.xml"
    xml.write_text(
        '<case><simulationdomain><posmin x="0" y="0" z="0" />'
        '<posmax x="1" y="1" z="1" /></simulationdomain></case>\n',
        encoding="utf-8",
    )
    run_out = tmp_path / "Run.out"
    run_out.write_text("MapRealPos(final)=(0,0,0)-(1,1,1)\n", encoding="utf-8")
    runparts = tmp_path / "RunPARTs.csv"
    runparts.write_text(
        "Part;NpOut;NpOutPos;NpOutRho;NpOutMov\n"
        "0;1;1;0;0\n"
        "# Part: legend\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.json"
    ledger.write_text(
        json.dumps({
            "native_exclusion_ledger": {
                "excluded_particles_reported_by_run_out": 1,
                "excluded_particles": [{
                    "idp": 7, "motive": "native_solver_excluded_numerical_unknown",
                    "position_m": [0.00001, 0.2, 0.3],
                    "first_missing_frame": 1, "first_missing_time_s": 0.1,
                }],
            },
        }),
        encoding="utf-8",
    )
    result = DOMAIN.classify_case(
        case_id="TEST", ledger_path=ledger, xml_path=xml,
        runparts_path=runparts, run_out_path=run_out, tolerance_m=5e-4,
    )
    assert result["simulation_domain"]["xml_and_run_out_match"] is True
    assert result["nearest_domain_face_counts"] == {"xmin": 1}
    assert result["interpretation"]["physical_spill"] == "not_classified_by_this_diagnostic"
    assert result["runparts_counts"]["NpOut"]["sum"] == 1.0
