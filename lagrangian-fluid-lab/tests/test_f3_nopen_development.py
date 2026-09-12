import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from scripts import f3_development_candidates as candidates
from scripts import f3_nopen_development as development
from scripts import l1r_branch_runner as runner

# Reuse the isolated native/qualification fixtures, never real solver artifacts.
from test_f3_nopen_qualification import campaign as qualification_campaign, dump, make_gate


@pytest.fixture
def dev_campaign(qualification_campaign, monkeypatch):
    campaign = qualification_campaign
    q = campaign["q"]
    d = development
    monkeypatch.setattr(d, "LAB", q.LAB)
    monkeypatch.setattr(d, "OUT", q.OUT)
    calls = []
    monkeypatch.setattr(d, "check_budget", lambda *, category: calls.append(category))
    monkeypatch.setattr(d, "check_input", q.check_input)
    nominal, _, _ = make_gate(campaign, "nominal")
    endpoints, _, _ = make_gate(campaign, "endpoints")
    internal = []
    for label in ("NP13", "NP14"):
        record = q.prepare(label)
        campaign["completed"](record)
        internal.append(record["id"])
    score_path = q.OUT / "fixture-domain-scores.json"
    dump(score_path, {"case_ids": internal, "metrics": {"maximum": .001}})
    bindings = dict(endpoints["evidence_sha256"])
    bindings.update(nominal["evidence_sha256"])
    paths = [q.OUT / name for name in ("F3-NOPEN-NOMINAL-GATE.json", "F3-NOPEN-ENDPOINT-GATE.json")]
    paths += [q.OUT / (name + "-AUDIT.json") for name in internal] + [score_path]
    bindings.update({q._relative(path): q.q2.sha256(path) for path in paths})
    domain = dict(schema="f3.nopen.domain_gate.v1", stage="domain", status="passed", recipe_id=q.RECIPE,
                  case_ids=internal, evidence_sha256=bindings, scoring_evidence_paths=[q._relative(score_path)],
                  production_resolution_m=.01, time_window_s=[0, 8.35], scoring_interval_s=.01)
    dump(q.OUT / d.DOMAIN_GATE, domain)
    generator = q.LAB / "scripts/f3_development_candidates.py"
    generator.write_bytes(Path(candidates.__file__).read_bytes())
    inputs = q.LAB / "campaigns/l1-resume/data/f3-development-inputs"
    inputs.mkdir(parents=True)
    rows = candidates.candidates()
    for row in rows:
        values = campaign["nominal"].copy()
        gravity = np.array([0., 0., -9.81])
        values[:, 1:4] = gravity + row["drive_amplitude"] * (values[:, 1:4] - gravity)
        values[:, 4:7] *= row["drive_amplitude"]
        path = inputs / (row["case_id"] + ".csv")
        np.savetxt(path, values, delimiter=";", fmt="%.17g", header="original independent forcing")
        effective = candidates.semantic_hash(values)
        lineage = hashlib.sha256(json.dumps({"initial": candidates.INITIAL, "effective_control_sha256": effective},
                                           sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        row.update(control_path=q._relative(path), control_file_sha256=q.q2.sha256(path),
                   effective_control_sha256=effective, physical_lineage_sha256=lineage)
    manifest = dict(status="inputs_registered_no_fluid_data", launch_allowed=False,
                    initial_physical_definition=candidates.INITIAL, cases=rows,
                    source_drive_sha256=campaign["base"]["drive_sha256"], program_sha256=q.q2.sha256(generator))
    dump(q.OUT / d.MANIFEST, manifest)

    def completed(record):
        audit = campaign["completed"](record)
        path = q.OUT / (record["id"] + "-SOLVER.json")
        solver = json.loads(path.read_text())
        solver["resource_category"] = "development"
        dump(path, solver)
        return audit

    return dict(campaign, d=d, rows=rows, manifest=manifest, domain=domain, score_path=score_path,
                development_budget_calls=calls, completed_development=completed)


def test_exact_candidate_csv_and_amplitude_are_preserved(dev_campaign):
    d = dev_campaign["d"]
    row = dev_campaign["rows"][0]
    assert row["drive_amplitude"] != round(row["drive_amplitude"], 6)
    manifest_before = (d.OUT / d.MANIFEST).read_bytes()
    record = d.prepare(row["case_id"])
    source = d.LAB / row["control_path"]
    target = (d.LAB / record["generated_prefix"]).parent / "CaseSloshingAccData.csv"
    assert target.read_bytes() == source.read_bytes()
    assert record["drive_amplitude"] == row["drive_amplitude"]
    assert record["drive_sha256"] == row["control_file_sha256"]
    assert record["effective_control_sha256"] == row["effective_control_sha256"]
    assert record["physical_lineage_sha256"] == row["physical_lineage_sha256"]
    assert record["resource_category"] == "development"
    assert record["max_attempts"] == 1 and record["solver_timeout_seconds"] == 1800
    assert record["gencase"]["fluid_particles"] == 14580 and record["gencase"]["boundary_particles"] == 42480
    assert record["native_velocity_displacement_correction"] is True and record["qualified"] is False
    assert (d.OUT / d.MANIFEST).read_bytes() == manifest_before
    assert d.prepare(row["case_id"]) == record
    assert dev_campaign["development_budget_calls"] == ["development", "development"]


def test_qualification_identity_cannot_be_relabelled_as_development(dev_campaign):
    d = dev_campaign["d"]
    with pytest.raises(ValueError, match="independent registered development"):
        d.prepare(dev_campaign["q"].NAME)
    assert dev_campaign["development_budget_calls"] == []
    assert not (d.OUT / d.REGISTRY).exists()


@pytest.mark.parametrize("change", ["status", "resolution_missing", "resolution_changed", "window", "missing_prerequisite", "scoring_coverage", "changed_score"])
def test_domain_gate_must_provide_real_bound_production_scope(dev_campaign, change):
    d = dev_campaign["d"]
    gate = copy.deepcopy(dev_campaign["domain"])
    if change == "status":
        gate["status"] = "failed"
    elif change == "resolution_missing":
        gate.pop("production_resolution_m")
    elif change == "resolution_changed":
        gate["production_resolution_m"] = .0075
    elif change == "window":
        gate["time_window_s"] = [0, 1.5]
    elif change == "missing_prerequisite":
        del gate["evidence_sha256"][d._relative(d.OUT / "F3-NOPEN-NOMINAL-GATE.json")]
    elif change == "scoring_coverage":
        dump(dev_campaign["score_path"], {"case_ids": gate["case_ids"][:1]})
        gate["evidence_sha256"][d._relative(dev_campaign["score_path"])] = d.q2.sha256(dev_campaign["score_path"])
    else:
        dev_campaign["score_path"].write_text(dev_campaign["score_path"].read_text() + " ")
    dump(d.OUT / d.DOMAIN_GATE, gate)
    with pytest.raises(ValueError):
        d.prepare(dev_campaign["rows"][0]["case_id"])
    assert not (d.OUT / d.REGISTRY).exists()


@pytest.mark.parametrize("change", ["csv", "lineage", "duplicate_control"])
def test_independent_input_identity_is_verified_before_registration(dev_campaign, change):
    d = dev_campaign["d"]
    manifest = copy.deepcopy(dev_campaign["manifest"])
    row = manifest["cases"][0]
    if change == "csv":
        path = d.LAB / row["control_path"]
        path.write_bytes(path.read_bytes() + b"# changed bytes\n")
    elif change == "lineage":
        row["physical_lineage_sha256"] = "invalid lineage"
    else:
        row["effective_control_sha256"] = manifest["cases"][1]["effective_control_sha256"]
    dump(d.OUT / d.MANIFEST, manifest)
    with pytest.raises(ValueError):
        d.prepare(row["case_id"])
    assert not (d.OUT / d.REGISTRY).exists()


def test_pilot_membership_is_read_from_manifest_flags(dev_campaign):
    d = dev_campaign["d"]
    manifest = copy.deepcopy(dev_campaign["manifest"])
    manifest["cases"][0]["pilot"] = False
    manifest["cases"][1]["pilot"] = True
    dump(d.OUT / d.MANIFEST, manifest)
    d.prepare(manifest["cases"][1]["case_id"])
    registry = json.loads((d.OUT / d.REGISTRY).read_text())
    assert registry["pilot_case_ids"] == [r["case_id"] for r in manifest["cases"] if r["pilot"]]
    assert manifest["cases"][0]["case_id"] not in registry["pilot_case_ids"]


def test_nonpilot_does_not_launch_until_all_eight_original_pilots_pass(dev_campaign, monkeypatch):
    d = dev_campaign["d"]
    rows = dev_campaign["rows"]
    target = next(r["case_id"] for r in rows if not r["pilot"])
    calls = []

    def execute(record):
        calls.append(record["id"])
        return dev_campaign["completed_development"](record)

    monkeypatch.setattr(runner, "run", execute)
    with pytest.raises(FileNotFoundError):
        d.run(target)
    assert calls == []
    pilot = [r for r in rows if r["pilot"]]
    for row in pilot:
        record = d.prepare(row["case_id"])
        dev_campaign["completed_development"](record)
    # All eight exist; one failed source must still prevent expansion. An extra
    # prepared nonpilot case cannot replace this member of the fixed pilot set.
    failed = d.OUT / (pilot[0]["case_id"] + "-AUDIT.json")
    good = json.loads(failed.read_text())
    bad = dict(good, audit_status="quality_failed", issues=["crossing"])
    dump(failed, bad)
    with pytest.raises(ValueError, match="source hard audit failed"):
        d.run(target)
    assert calls == []
    dump(failed, good)
    result = d.run(target)
    assert calls == [target]
    assert result["status"] == "completed" and result["resource_category"] == "development"
    assert result["remaining_cases_launched"] is False


@pytest.mark.parametrize("change", ["category", "source_record", "native_log", "hdf5"])
def test_verified_development_checks_actual_solver_and_complete_source(dev_campaign, change):
    d = dev_campaign["d"]
    name = dev_campaign["rows"][0]["case_id"]
    record = d.prepare(name)
    dev_campaign["completed_development"](record)
    assert d.verified_development(name)[0]["case_id"] == name
    solver_path = d.OUT / (name + "-SOLVER.json")
    solver = json.loads(solver_path.read_text())
    if change == "category":
        solver["resource_category"] = "qualification"
        dump(solver_path, solver)
    elif change == "source_record":
        solver["source_record"]["physical_lineage_sha256"] = "other lineage"
        dump(solver_path, solver)
    elif change == "native_log":
        (Path(solver["attempt_directory"]) / "Run.out").write_text('SlipMode="No-slip"\nNo Penetration=False\n')
    else:
        audit = json.loads((d.OUT / (name + "-AUDIT.json")).read_text())
        (d.LAB / audit["hdf5"]).write_bytes(b"changed source states")
    with pytest.raises(ValueError):
        d.verified_development(name)


def test_completed_verification_has_no_registration_or_budget_writes(dev_campaign):
    d = dev_campaign["d"]
    name = dev_campaign["rows"][0]["case_id"]
    record = d.prepare(name)
    dev_campaign["completed_development"](record)
    before = {p: p.read_bytes() for p in d.OUT.glob("*.json")}
    budget_count = len(dev_campaign["development_budget_calls"])
    d.verified_development(name)
    assert {p: p.read_bytes() for p in d.OUT.glob("*.json")} == before
    assert len(dev_campaign["development_budget_calls"]) == budget_count


@pytest.mark.parametrize("change", ["pilot_set", "native_counts", "source_prefix"])
def test_development_registry_cannot_change_pilots_or_native_initial_source(dev_campaign, change):
    d = dev_campaign["d"]
    name = dev_campaign["rows"][0]["case_id"]
    d.prepare(name)
    path = d.OUT / d.REGISTRY
    registry = json.loads(path.read_text())
    if change == "pilot_set":
        registry["pilot_case_ids"] = registry["pilot_case_ids"][1:]
    elif change == "native_counts":
        registry["initial_source"]["fluid_particles"] = 34560
    else:
        registry["initial_source"]["prefix"] = "other/unqualified/initial"
    dump(path, registry)
    with pytest.raises(ValueError):
        d.prepare(name)


def test_failed_pilot_run_reports_failure_without_automatic_replacement(dev_campaign, monkeypatch):
    d = dev_campaign["d"]
    name = dev_campaign["rows"][0]["case_id"]
    calls = []

    def failed(record):
        calls.append(record["id"])
        return dict(case_id=record["id"], status="failed", audit_status="quality_failed", issues=["lost_particle"], unknowns=[])

    monkeypatch.setattr(runner, "run", failed)
    result = d.run(name)
    assert result["status"] == "failed" and result["hard_audit_passed"] is False
    assert result["remaining_cases_launched"] is False and calls == [name]


def test_development_cli_returns_nonzero_for_hard_failure(monkeypatch):
    monkeypatch.setattr(development, "run", lambda name: {"hard_audit_passed": False})
    assert development.main(["run", "F3_DEV_00_a0p903125"]) == 1
