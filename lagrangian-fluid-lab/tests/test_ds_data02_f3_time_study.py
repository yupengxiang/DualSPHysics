import json
from pathlib import Path

import h5py
import numpy as np

from scripts import ds_data02_f3_time_study as study


ROOT = Path(__file__).resolve().parents[1]
F3 = ROOT / "campaigns/ds-data-02/families/F3"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_DUAL_AXIS_WEAK_006G_004G")


def _minimal_h5(path: Path, offset: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    times = np.array([0.0, 5.0, 10.0])
    # Two fixed identities and two fluid identities; the fluid COM is shifted
    # by ``offset`` in the candidate so the comparison must report a difference.
    positions = np.zeros((3, 4, 3), dtype=np.float64)
    positions[:, 2, 0] = np.array([0.0, 0.5, 1.0]) + offset
    positions[:, 3, 0] = np.array([1.0, 1.5, 2.0]) + offset
    velocity = np.zeros_like(positions)
    velocity[:, 2, 0] = 0.1
    velocity[:, 3, 0] = 0.2
    valid = np.ones((3, 4), dtype=np.bool_)
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=times)
        h5.create_dataset("initial_type", data=np.array([0, 0, 3, 3], dtype=np.int8))
        h5.create_dataset("initial_mass", data=np.full(4, 0.5))
        h5.create_dataset("valid", data=valid)
        h5.create_dataset("mass", data=np.full((3, 4), 0.5))
        h5.create_dataset("position", data=positions)
        h5.create_dataset("velocity", data=velocity)
        h5.attrs["coordinate_frame"] = "fixed_tank_acceleration"


def test_real_baseline_dt_and_population_are_registered():
    result = study.measure_baseline(
        DATA / "qualification-weak-dual-scope-001/solver_output/RunPARTs.csv",
        DATA / "qualification-weak-dual-scope-001/solver_output/Run.csv",
        DATA / "qualification-weak-dual-scope-001/solver_output/Run.out",
    )
    assert result["runparts"]["saved_frames"] == 4001
    assert result["runparts"]["initial_fluid_particles"] == 34560
    assert result["runparts"]["npout_sum"] == 0
    assert result["runparts"]["native_minimum_dt_s"] == study.BASELINE_DT_MIN_S
    assert result["runparts"]["time_end_s"] > 10.0
    assert result["run_out_parameters"]["time_out_s"] == study.BASELINE_SAVE_S
    assert result["run_out_parameters"]["time_out_source_label"] == "TimePart"


def test_native_accounting_parser_exposes_run_out_steps_and_dt(tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"status": "completed", "returncode": 0, "gpu_seconds": 0.0, "command": []}))
    runparts = tmp_path / "RunPARTs.csv"
    runparts.write_text(
        "Part;TimeStep [s];NpOut;Steps;DtMin [s];DtMax [s];NpSim;NpfSim\n"
        "0;1;0;10;0.1;0.2;10;4\n"
        "1;2;0;20;0.1;0.2;10;4\n"
    )
    run_csv = tmp_path / "Run.csv"
    run_csv.write_text("Steps;PhysicalTime;PartFiles;Np;Dp;Configuration\n30;2;2;10;0.1;test\n")
    run_out = tmp_path / "Run.out"
    run_out.write_text(
        "**3D-Simulation parameters\nDtMin=0.1\nTimePart=1\nTimeMax=2\n"
        "Steps of simulation.................: 30\n"
    )
    output = tmp_path / "native.json"
    result = study.make_native_accounting(type("Args", (), {
        "case_id": "F3_DUAL_AXIS_WEAK_006G_004G",
        "attempt_id": "test",
        "solver_receipt": receipt,
        "runparts": runparts,
        "run_csv": run_csv,
        "run_out": run_out,
        "output": output,
    })())
    facts = result["facts"]
    assert facts["run_out_parameters"]["dt_min_s"] == 0.1
    assert facts["run_out_parameters"]["steps_of_simulation"] == 30


def test_fixed_window_comparison_records_brackets_and_error(tmp_path):
    baseline = tmp_path / "baseline.h5"
    candidate = tmp_path / "candidate.h5"
    output = tmp_path / "comparison.json"
    _minimal_h5(baseline)
    _minimal_h5(candidate, offset=0.1)
    result = study.compare_fixed_window(
        type("Args", (), {"baseline": baseline, "variant": [candidate], "grid_step": 2.5, "output": output})()
    )
    row = result["comparisons"][candidate.stem]
    assert row["times"]["frame_count"] == 3
    assert len(row["time_brackets"]) == 5
    assert row["macro_error"]["com_x_m"]["max_abs"] > 0
    assert result["claim_boundary"].endswith("Q-N and production remain unassessed")


def test_variant_patch_preserves_physical_hash_and_changes_only_numeric_fields(tmp_path):
    owner_path = F3 / "weak_dual_scope_001/f3_weak_owner_metadata.json"
    owner = json.loads(owner_path.read_text())
    owner["_path"] = str(owner_path)
    baseline = study.measure_baseline(
        DATA / "qualification-weak-dual-scope-001/solver_output/RunPARTs.csv",
        DATA / "qualification-weak-dual-scope-001/solver_output/Run.csv",
        DATA / "qualification-weak-dual-scope-001/solver_output/Run.out",
    )
    output = tmp_path / "source"
    result = study._write_variant(
        Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/weak_dual_scope_001/F3_DUAL_AXIS_WEAK_006G_004G_Def.xml"),
        DATA / "gencase-weak-dual-scope-001/F3_DualAxisPhase_WeakControl.csv",
        output,
        "half_dt",
        baseline,
        owner,
    )
    assert result["physical_binding_sha256"] == study.PHYSICAL_BINDING_SHA
    root = study.ET.parse(result["variant_definition"]["path"]).getroot()
    assert study._parameter(root, "DtFixed").get("value") == "1.106134843353494e-05"
    assert study._parameter(root, "TimeOut").get("value") == "0.0025"


def test_prepare_solver_input_resolves_xml_relative_control_without_rewriting_sources(tmp_path):
    xml = tmp_path / "generated.xml"
    bi4 = tmp_path / "generated.bi4"
    control = tmp_path / "F3_DualAxisPhase_WeakControl.csv"
    receipt = tmp_path / "gencase-receipt.json"
    output = tmp_path / "prepared"
    report = output / "prepared-source-manifest.json"
    xml.write_text(
        '<case><execution><commands><motion><acctimesfile value="F3_DualAxisPhase_WeakControl.csv" /></motion></commands>'
        '<data2d value="false" /><normals active="true" /><particles np="108000" /></execution>'
        '<parameter key="DtIni" value="0" /><parameter key="DtMin" value="0" />'
        '<parameter key="DtFixed" value="0" /><parameter key="DtFixedFile" value="NONE" />'
        '<parameter key="TimeMax" value="10" /><parameter key="TimeOut" value="0.0025" /></case>'
    )
    bi4.write_bytes(b"native-bi4-placeholder")
    # The production helper checks the frozen control hash.  Use a real
    # source copy so this test exercises the actual copy/relative-path logic.
    source_control = DATA / "gencase-weak-dual-scope-001/F3_DualAxisPhase_WeakControl.csv"
    control.write_bytes(source_control.read_bytes())
    receipt.write_text(json.dumps({"status": "completed", "returncode": 0, "solver_dimension_from_gencase": 3,
                                   "fluid_particles": 34560, "total_particles": 108000,
                                   "output_root": str(tmp_path)}))
    source_xml_bytes = xml.read_bytes()
    source_bi4_bytes = bi4.read_bytes()
    source_control_bytes = control.read_bytes()
    args = type("Args", (), {
        "case_id": "F3_TEST_PREPARED",
        "generated_xml": xml, "generated_bi4": bi4, "control": control,
        "gencase_receipt": receipt, "output_dir": output, "output_report": report,
    })()
    result = study.prepare_solver_input(args)
    assert result["control_reference"]["matches"] is True
    assert (output / "F3_TEST_PREPARED.xml").read_bytes() == source_xml_bytes
    assert (output / "F3_TEST_PREPARED.bi4").read_bytes() == source_bi4_bytes
    assert (output / "F3_DualAxisPhase_WeakControl.csv").read_bytes() == source_control_bytes
    assert xml.read_bytes() == source_xml_bytes
    assert bi4.read_bytes() == source_bi4_bytes
    assert control.read_bytes() == source_control_bytes
