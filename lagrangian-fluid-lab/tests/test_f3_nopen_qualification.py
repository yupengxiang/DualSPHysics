import copy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from scripts import f3_nopen_qualification as qualification
from scripts import l1r_branch_runner as runner
from scripts import l1r_input_preflight as preflight


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def xml_input(dp, n, nb, *, nopen=False):
    root = ET.Element("case")
    definition = ET.SubElement(ET.SubElement(root, "casedef"), "constantsdef")
    ET.SubElement(definition, "cflnumber", value=".05")
    geometry = ET.SubElement(root.find("casedef"), "geometry")
    ET.SubElement(geometry, "definition", dp=str(dp))
    execution = ET.SubElement(root, "execution")
    special = ET.SubElement(execution, "special")
    ET.SubElement(special, "forcing", file="CaseSloshingAccData.csv")
    params = ET.SubElement(execution, "parameters")
    values = dict(Boundary=2, SlipMode=2 if nopen else 1, NoPenetration=int(nopen),
                  Visco=.05, ViscoBoundFactor=1 if nopen else 0, Shifting=0,
                  StepAlgorithm=2, Kernel=2, DensityDT=3, TimeMax=8.35 if nopen else 1.5,
                  TimeOut=.01, CoefDtMin=.05, DtFixed=0)
    for key, value in values.items():
        ET.SubElement(params, "parameter", key=key, value=str(value))
    particles = ET.SubElement(execution, "particles", np=str(n + nb), nb=str(nb), nbf=str(nb))
    ET.SubElement(particles, "fixed", begin="0", count=str(nb))
    ET.SubElement(particles, "fluid", begin=str(nb), count=str(n))
    constants = ET.SubElement(execution, "constants")
    for key, value in dict(dp=dp, h=1.59217038 * dp, cflnumber=.05, massfluid=1000 * dp**3).items():
        ET.SubElement(constants, key, value=str(value))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    q = qualification
    out = tmp_path / "campaigns/l1-resume/continuation"
    out.mkdir(parents=True)
    monkeypatch.setattr(q, "LAB", tmp_path)
    monkeypatch.setattr(q, "OUT", out)
    monkeypatch.setattr(preflight, "LAB", tmp_path)
    budget_calls, preflight_calls = [], []
    monkeypatch.setattr(q, "check_budget", lambda: budget_calls.append("checked"))
    binary = tmp_path / "native-solver"
    binary.write_bytes(b"fixture solver: never executed")
    monkeypatch.setattr(q.q2, "SOLVER", binary)
    nominal = np.array([[0., 0., 0., -9.81, 0., 0., 0.],
                        [4., .2, 0., -9.8, 0., .1, 0.],
                        [8.35, -.1, 0., -9.79, 0., -.2, 0.]])
    original_plan = {
        "scope": "conditional_plan_not_authorization", "launch_allowed": False, "recipe_id": q.RECIPE,
        "cases": [dict(plan_case_id=name, **dict(zip(q.KEYS, values)), time_window_s=[0, 8.35],
                       launch_allowed_via_this_plan=False, roles=[name]) for name, values in q.EXPECTED.items()],
    }
    dump(out / q.PLAN, original_plan)
    dump(out / "RESOURCE-LIMITS.json", {
        "limits": {"qualification": 72},
        "authorization_history": [{"owner_reply": "批准资格求解总上限 72 次",
                                    "change": {"qualification": {"before": 56, "after": 72}}}],
    })
    operator = tmp_path / "scripts/f3_observation_v2.py"
    operator.parent.mkdir()
    operator.write_text("fixture frozen operator\n")
    dump(tmp_path / "diagnostics/f3-audit/v2-calibration.json",
         {"calibrated": True, "operator_sha256": q.q2.sha256(operator)})
    dump(out / "F3-V2-OBSERVATION-DESIGN.json", {"frozen": True})
    native_source = tmp_path / "native.cpp"
    native_source.write_text("fixture unchanged native source\n")
    dump(out / "F3-NATIVE-NOPEN-DESIGN.json", {"native_source_hashes": {"native.cpp": q.q2.sha256(native_source)}})

    def initial_state(prefix, dp):
        counts = q._xml_metadata(prefix, dp)
        return dict(counts, initial_mass_kg=14.58, initial_com_m=[0., 0., .045],
                    native_dp_m=dp, zero_boundary_normals=0)

    # All generated/native source counts are independently fixed in this fixture;
    # no solver or native BI4 decoder runs in unit tests.
    monkeypatch.setattr(q, "_initial_state", initial_state)
    for dp, n, nb in ((.01, 14580, 42480), (.0075, 34560, 73440), (.006, 67500, 111708)):
        basename = "F3_CELL3_plain_" + str(dp).replace(".", "p")
        folder = tmp_path / "campaigns/l1-resume/artifacts/cell3" / basename
        folder.mkdir(parents=True)
        for ext in (".xml", "_Def.xml"):
            (folder / (basename + ext)).write_bytes(xml_input(dp, n, nb))
        (folder / (basename + ".bi4")).write_text(f"original native BI4 for dp={dp}; n={n}; nb={nb}\n")
        (folder / (basename + "_hdp_Actual.vtk")).write_text(f"physical normal geometry dp={dp}\n")
        np.savetxt(folder / "CaseSloshingAccData.csv", nominal, delimiter=";", fmt="%.17g")
    basename = "F3_CELL3_plain_0p01"
    source = tmp_path / "campaigns/l1-resume/artifacts/cell3" / basename
    base_folder = tmp_path / "campaigns/l1-resume/artifacts/cell3-long" / q.NAME
    base_folder.mkdir(parents=True)
    for path in source.iterdir():
        (base_folder / path.name).write_bytes(path.read_bytes())
    for ext in (".xml", "_Def.xml"):
        (base_folder / (basename + ext)).write_bytes(xml_input(.01, 14580, 42480, nopen=True))
    base = dict(id=q.NAME, case_id=q.NAME, family="F3", background_id="plain", recipe_id=q.RECIPE,
                solver_mode="-mdbc_noslip:1", expected_slip_mode="No-slip", expected_no_penetration=True,
                dp_m=.01, drive_amplitude=1., time_out_s=.01, time_max_s=8.35,
                cfl_number=.05, coef_dt_min=.05, max_attempts=1,
                generated_prefix=q._relative(base_folder / basename),
                candidate_definition=q._relative(base_folder / (basename + "_Def.xml")),
                gencase=dict(total_particles=57060, fluid_particles=14580, boundary_particles=42480),
                wall_spec={"obstacles": [], "closed_faces": ["bottom", "left", "right", "front", "back"]},
                boundary_bridge_sha256=q.q2.sha256(out / "F3-NATIVE-NOPEN-DESIGN.json"),
                control_definition="F3_CELL3_gravity_preserving_amplitude_v1",
                drive_sha256=q.q2.sha256(base_folder / "CaseSloshingAccData.csv"),
                input_assets={p.name: q.q2.sha256(p) for p in base_folder.iterdir()},
                generated_xml_sha256=q.q2.sha256(base_folder / (basename + ".xml")))
    dump(out / (q.NAME + "-PREPARED.json"), base)

    def completed(record):
        name = record["id"]
        h5 = tmp_path / "campaigns/l1-resume/data/continuation" / (name + ".h5")
        h5.parent.mkdir(parents=True, exist_ok=True)
        h5.write_bytes(("fixture audit-bound states " + name).encode())
        n = record["gencase"]["fluid_particles"]
        audit = dict(case_id=name, dp_m=record["dp_m"], audit_status="pass_diagnostic", issues=[], unknowns=[],
                     frames=round(8.35 / record["time_out_s"]) + 1, time_start_s=0, time_end_s=8.35001,
                     particle_axis_count=n, initial_valid_particles=n, final_valid_particles=n,
                     identities_introduced_after_initial=0, initial_identities_missing_at_final=0,
                     identities_reappeared_after_gap=0, excluded_particles_from_solver_log=0, finite_bad_value_rows=0,
                     penetration=dict(frames_with_penetration=0, frames_with_runtime_domain_outside=0,
                                      swept_crossing_count=0, runtime_domain_status="checked"),
                     hdf5=q._relative(h5), hdf5_sha256=q.q2.sha256(h5))
        dump(out / (name + "-AUDIT.json"), audit)
        attempt = tmp_path / "campaigns/l1-resume/runs/branches" / name / "attempts/fixture.complete"
        attempt.mkdir(parents=True, exist_ok=True)
        (attempt / "Run.out").write_text('SlipMode="No-slip"\nNo Penetration=True\nFinished execution (code=0)\n')
        solver = dict(case_id=name, status="completed", attempt_directory=str(attempt),
                      solver_sha256=q.q2.sha256(binary), source_record=copy.deepcopy(record))
        dump(out / (name + "-SOLVER.json"), solver)
        return audit

    completed(base)

    def input_preflight(record):
        preflight_calls.append(record["id"])
        preflight.check_boundary_mode(record)
        path = tmp_path / record["generated_prefix"]
        actual = np.loadtxt(path.parent / "CaseSloshingAccData.csv", delimiter=";", comments="#")
        expected = nominal.copy()
        gravity = np.array([0., 0., -9.81])
        expected[:, 1:4] = gravity + record["drive_amplitude"] * (nominal[:, 1:4] - gravity)
        expected[:, 4:] *= record["drive_amplitude"]
        if not np.array_equal(expected, actual):
            raise ValueError("incorrect gravity-preserving control")

    monkeypatch.setattr(q, "check_input", input_preflight)
    monkeypatch.setattr(runner, "run", lambda record: pytest.fail("unit test attempted to use the real shared runner"))
    return dict(q=q, out=out, root=tmp_path, base=base, completed=completed, nominal=nominal,
                budget_calls=budget_calls, preflight_calls=preflight_calls)


def test_read_only_lookup_and_no_np01_relaunch(campaign):
    q = campaign["q"]
    before = set(campaign["out"].iterdir())
    assert q.case_id_for("NP01") == q.NAME
    assert q.case_id_for("NP05") == "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen"
    assert q.plan_entry("NP14")["amplitude"] == .97
    assert set(campaign["out"].iterdir()) == before
    assert campaign["budget_calls"] == []
    with pytest.raises(ValueError, match="separate one-attempt"):
        q.prepare("NP01")
    with pytest.raises(ValueError, match="unknown qualification"):
        q.plan_entry("NP15")


@pytest.mark.parametrize("plan_id", [f"NP{i:02}" for i in range(2, 15)])
def test_prepare_preserves_dp_native_assets_and_single_factor_parameters(campaign, plan_id):
    q = campaign["q"]
    before_plan = (q.OUT / q.PLAN).read_bytes()
    record = q.prepare(plan_id)
    entry = q.plan_entry(plan_id)
    prefix = q.LAB / record["generated_prefix"]
    root = ET.parse(prefix.with_suffix(".xml")).getroot()
    params = q._parameters(root)
    assert {k: float(params[k]) for k in ("NoPenetration", "SlipMode", "ViscoBoundFactor", "Visco", "Shifting")} == {
        "NoPenetration": 1., "SlipMode": 2., "ViscoBoundFactor": 1., "Visco": .05, "Shifting": 0.,
    }
    assert float(params["TimeMax"]) == 8.35
    assert float(params["TimeOut"]) == entry["output_interval_s"]
    assert float(params["CoefDtMin"]) == entry["coef_dt_min"]
    assert all(float(n.get("value")) == entry["cfl_number"] for n in root.findall(".//cflnumber"))
    counts = {.01: (14580, 42480), .0075: (34560, 73440), .006: (67500, 111708)}
    n, nb = counts[entry["dp_m"]]
    assert record["gencase"]["fluid_particles"] == n
    assert record["gencase"]["boundary_particles"] == nb
    assert record["gencase"]["total_particles"] == n + nb
    assert float(root.find("./execution/constants/dp").get("value")) == entry["dp_m"]
    source = q.LAB / record["gencase"]["reuse_source"] / prefix.name
    assert prefix.with_suffix(".bi4").read_bytes() == source.with_suffix(".bi4").read_bytes()
    assert record["max_attempts"] == 1
    assert record["recipe_id"] == q.RECIPE and record["qualified"] is False
    assert record["native_velocity_displacement_correction"] is True
    assert (q.OUT / q.PLAN).read_bytes() == before_plan
    stage = json.loads((q.OUT / q.STAGE).read_text())
    assert stage["approved_qualification_cap_at_registration"] == 72
    assert stage["conditional_plan"]["sha256"] == q.q2.sha256(q.OUT / q.PLAN)
    assert q.prepare(plan_id) == record


def test_zero_control_keeps_gravity_and_zeroes_only_perturbation(campaign):
    q = campaign["q"]
    record = q.prepare("NP02")
    values = np.loadtxt((q.LAB / record["generated_prefix"]).parent / "CaseSloshingAccData.csv", delimiter=";", comments="#")
    assert np.array_equal(values[:, 0], campaign["nominal"][:, 0])
    assert np.array_equal(values[:, 1:4], np.tile([0., 0., -9.81], (len(values), 1)))
    assert np.count_nonzero(values[:, 4:]) == 0


@pytest.mark.parametrize("change", ["cap", "plan", "source_h5", "native_log", "source_execution"])
def test_prepare_rejects_unapproved_or_changed_prerequisites(campaign, change):
    q = campaign["q"]
    if change == "cap":
        dump(q.OUT / "RESOURCE-LIMITS.json", {"limits": {"qualification": 64}})
    elif change == "plan":
        plan = json.loads((q.OUT / q.PLAN).read_text())
        plan["cases"][4]["dp_m"] = .01
        dump(q.OUT / q.PLAN, plan)
    elif change == "source_h5":
        path = q.LAB / "campaigns/l1-resume/data/continuation" / (q.NAME + ".h5")
        path.write_bytes(path.read_bytes() + b"changed")
    else:
        solver = json.loads((q.OUT / (q.NAME + "-SOLVER.json")).read_text())
        if change == "native_log":
            (Path(solver["attempt_directory"]) / "Run.out").write_text('SlipMode="No-slip"\nNo Penetration=False\n')
        else:
            solver["source_record"]["gencase"]["fluid_particles"] = 1
            dump(q.OUT / (q.NAME + "-SOLVER.json"), solver)
    with pytest.raises(ValueError):
        q.prepare("NP02")
    assert not (q.OUT / q.STAGE).exists()


@pytest.mark.parametrize("change", ["attempt_cap", "bi4", "xml"])
def test_prepared_record_cannot_self_rehash_an_unregistered_change(campaign, change):
    q = campaign["q"]
    record = q.prepare("NP05")
    prefix = q.LAB / record["generated_prefix"]
    if change == "attempt_cap":
        record["max_attempts"] = 2
    elif change == "bi4":
        path = prefix.with_suffix(".bi4")
        path.write_bytes(b"wrong native geometry")
        record["input_assets"][path.name] = q.q2.sha256(path)
    else:
        path = prefix.with_suffix(".xml")
        tree = ET.parse(path)
        tree.find('./execution/parameters/parameter[@key="Visco"]').set("value", ".1")
        tree.write(path)
        record["input_assets"][path.name] = q.q2.sha256(path)
        record["generated_xml_sha256"] = q.q2.sha256(path)
    dump(q.OUT / (record["id"] + "-PREPARED.json"), record)
    with pytest.raises(ValueError):
        q.prepare("NP05")


def test_incomplete_target_is_not_overwritten(campaign):
    q = campaign["q"]
    name = q.case_id_for("NP06")
    target = q.LAB / "campaigns/l1-resume/artifacts/cell3-nopen-qualification" / name
    target.mkdir(parents=True)
    (target / "partial-evidence").write_text("keep")
    with pytest.raises(ValueError, match="without overwriting"):
        q.prepare("NP06")
    assert (target / "partial-evidence").read_text() == "keep"


def make_gate(campaign, stage):
    q = campaign["q"]
    labels = [f"NP{i:02}" for i in (range(1, 7) if stage == "nominal" else range(7, 13))]
    names = []
    for label in labels:
        record = campaign["base"] if label == "NP01" else q.prepare(label)
        campaign["completed"](record)
        names.append(record["id"])
    scoring = q.OUT / ("fixture-" + stage + "-scores.json")
    dump(scoring, {"case_ids": names, "metrics": {"maximum": .001}})
    paths = [q.OUT / (name + "-AUDIT.json") for name in names] + [scoring]
    if stage == "endpoints":
        paths.append(q.OUT / "F3-NOPEN-NOMINAL-GATE.json")
    gate = dict(schema="f3.nopen.stage_gate.v1", stage=stage, status="passed", recipe_id=q.RECIPE,
                case_ids=names, evidence_sha256={q._relative(p): q.q2.sha256(p) for p in paths},
                scoring_evidence_paths=[q._relative(scoring)])
    filename = "F3-NOPEN-NOMINAL-GATE.json" if stage == "nominal" else "F3-NOPEN-ENDPOINT-GATE.json"
    dump(q.OUT / filename, gate)
    return gate, q.OUT / filename, scoring


def test_stage_gates_bind_all_audits_scores_and_nominal_predecessor(campaign):
    q = campaign["q"]
    nominal, _, _ = make_gate(campaign, "nominal")
    assert q.verify_stage_gate("nominal") == nominal
    endpoint, path, _ = make_gate(campaign, "endpoints")
    assert q.verify_stage_gate("endpoints") == endpoint
    del endpoint["evidence_sha256"][q._relative(q.OUT / "F3-NOPEN-NOMINAL-GATE.json")]
    dump(path, endpoint)
    with pytest.raises(ValueError, match="bind its passed nominal gate"):
        q.verify_stage_gate("endpoints")


@pytest.mark.parametrize("change", ["missing_audit", "changed_score", "incomplete_score_coverage", "boolean_only"])
def test_stage_pass_boolean_cannot_replace_bound_scoring(campaign, change):
    q = campaign["q"]
    gate, path, score = make_gate(campaign, "nominal")
    if change == "missing_audit":
        del gate["evidence_sha256"][q._relative(q.OUT / (q.NAME + "-AUDIT.json"))]
    elif change == "changed_score":
        score.write_text(score.read_text() + " ")
    elif change == "incomplete_score_coverage":
        dump(score, {"case_ids": gate["case_ids"][:-1], "metrics": {"maximum": .001}})
        gate["evidence_sha256"][q._relative(score)] = q.q2.sha256(score)
    else:
        gate.pop("scoring_evidence_paths")
    dump(path, gate)
    with pytest.raises(ValueError):
        q.verify_stage_gate("nominal")


def test_endpoint_run_requires_gate_before_preparation_or_runner(campaign):
    q = campaign["q"]
    with pytest.raises(FileNotFoundError):
        q.run("NP07")
    assert campaign["budget_calls"] == []
    assert not (q.OUT / (q.case_id_for("NP07") + "-PREPARED.json")).exists()


def test_single_run_returns_hard_failure_and_does_not_launch_more(campaign, monkeypatch):
    q = campaign["q"]
    calls = []

    def failed(record):
        calls.append(record)
        return dict(case_id=record["id"], audit_status="quality_failed", issues=["crossing"], unknowns=[])

    monkeypatch.setattr(runner, "run", failed)
    result = q.run("NP02")
    assert len(calls) == 1 and calls[0]["max_attempts"] == 1
    assert result["status"] == "failed" and result["hard_audit_passed"] is False
    assert result["remaining_matrix_launched"] is False and result["qualified"] is False
    assert not (q.OUT / (q.case_id_for("NP03") + "-PREPARED.json")).exists()


def test_single_run_pass_does_not_grant_production_qualification(campaign, monkeypatch):
    q = campaign["q"]
    monkeypatch.setattr(runner, "run", campaign["completed"])
    result = q.run("NP03")
    assert result["status"] == "completed" and result["hard_audit_passed"] is True
    assert result["frames"] == 836 and result["qualified"] is False


def test_cli_returns_nonzero_for_hard_failure(monkeypatch):
    monkeypatch.setattr(qualification, "run", lambda entry: {"hard_audit_passed": False, "status": "failed"})
    assert qualification.main(["run", "NP02"]) == 1
