"""Small manufactured trajectories; no real gate, CFD, ledger or training writes."""

import copy
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import types

import h5py
import numpy as np
import pytest

from scripts import f3_development_candidates as candidates
from scripts import f3_training_data as data
from scripts import f3_timestep_evidence as timesteps


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


@pytest.fixture
def manufactured(tmp_path, monkeypatch):
    """Mock only the already separately tested domain/native hard-source guard."""
    out = tmp_path / "campaigns/l1-resume/continuation"
    out.mkdir(parents=True)
    monkeypatch.setattr(data, "LAB", tmp_path)
    monkeypatch.setattr(data, "OUT", out)
    monkeypatch.setattr(timesteps, "LAB", tmp_path)
    monkeypatch.setattr(timesteps, "OUT", out)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in data.PROGRAMS:
        (scripts / name).write_bytes((Path(data.__file__).parent / name).read_bytes())
    nominal = np.array([[0., 0., 0., -9.81, 0., 0., 0.],
                        [4., .2, 0., -9.8, 0., .1, 0.],
                        [8.35, -.1, 0., -9.79, 0., -.2, 0.]])
    initial = tmp_path / "initial/Case"
    initial.parent.mkdir()
    initial.with_suffix(".xml").write_text("manufactured NoPen source: not CFD evidence\n")
    nominal_path = initial.parent / "CaseSloshingAccData.csv"
    np.savetxt(nominal_path, nominal, delimiter=";", fmt="%.17g")
    grid = data.target_grid(.01)
    native_times = grid.copy()
    native_times[1:] += .00001
    ids = np.array([420, 12, 700, 91], dtype=np.int64)
    masses = np.array([.1, .2, .3, .4])
    p0 = np.array([[.02, 0., .03], [.03, .01, .03], [.04, .02, .04], [.06, .01, .02]])
    slopes = np.arange(12).reshape(4, 3) * .002 + .01
    native_velocity = np.full((4, 3), 7.)  # Deliberately unlike derived velocity.
    rows = candidates.candidates()
    source_values = {}
    for row in rows:
        name = row["case_id"]
        control = tmp_path / "controls" / (name + ".csv")
        control.parent.mkdir(exist_ok=True)
        values = nominal.copy()
        gravity = np.array([0., 0., -9.81])
        values[:, 1:4] = gravity + row["drive_amplitude"] * (values[:, 1:4] - gravity)
        values[:, 4:] *= row["drive_amplitude"]
        np.savetxt(control, values, delimiter=";", fmt="%.17g")
        row.update(control_path=data._relative(control), control_file_sha256=data.sha256(control),
                   effective_control_sha256=candidates.semantic_hash(values),
                   physical_lineage_sha256=f"manufactured-physical-lineage-{row['index']}")
        prefix = tmp_path / "prepared" / name / "Case"
        prefix.parent.mkdir(parents=True)
        prefix.with_suffix(".xml").write_bytes(initial.with_suffix(".xml").read_bytes())
        drive = prefix.parent / "CaseSloshingAccData.csv"
        drive.write_bytes(control.read_bytes())
        h5_path = tmp_path / "data" / (name + ".h5")
        h5_path.parent.mkdir(exist_ok=True)
        p = p0 + native_times[:, None, None] * slopes + native_times[:, None, None]**2 * .001
        with h5py.File(h5_path, "w") as h:
            h["time"] = native_times
            h["particle_id"] = ids
            h["position"] = p
            h["velocity"] = np.broadcast_to(native_velocity, p.shape)
            h["mass"] = np.broadcast_to(masses, p.shape[:2])
            h["valid"] = np.ones(p.shape[:2], dtype=bool)
            h["type"] = np.full(p.shape[:2], 3, dtype=np.uint8)
        record = dict(id=name, case_id=name, generated_prefix=data._relative(prefix), dp_m=.01,
                      drive_amplitude=row["drive_amplitude"], drive_sha256=row["control_file_sha256"],
                      resource_category="development", recipe_id=data.development.RECIPE,
                      input_assets={p.name: data.sha256(p) for p in prefix.parent.iterdir()})
        audit = dict(case_id=name, audit_status="pass_diagnostic", issues=[], unknowns=[],
                     frames=len(grid), particle_axis_count=len(ids), time_start_s=0.,
                     time_end_s=float(native_times[-1]), initial_fluid_mass_kg=float(masses.sum()),
                     hdf5=data._relative(h5_path), hdf5_sha256=data.sha256(h5_path))
        attempt = tmp_path / "attempts" / name
        attempt.mkdir(parents=True)
        (attempt / "Run.out").write_text('SlipMode="No-slip"\nNo Penetration=True\n')
        (attempt / "RunPARTs.csv").write_text(
            "DtMin [s];DtMax [s];Steps;TimeStep [s]\n"
            f".000001;.00005;200000;{native_times[-1]:.17g}\n")
        solver = dict(case_id=name, status="completed", source_record=record,
                      attempt_directory=str(attempt), elapsed_seconds=1.)
        preflight = dict(status="passed", asset={"path": data._relative(drive), "sha256": data.sha256(drive)},
                         source={"path": data._relative(nominal_path), "sha256": data.sha256(nominal_path)},
                         native_reader={"first_time_s": 0., "last_time_s": 8.35, "rows": 3})
        for suffix, value in (("PREPARED", record), ("AUDIT", audit), ("SOLVER", solver), ("INPUT-PREFLIGHT", preflight)):
            dump(out / f"{name}-{suffix}.json", value)
        source_values[name] = dict(record=record, audit=audit, solver=solver)
    manifest = dict(cases=rows, source_drive_sha256=data.sha256(nominal_path))
    score = out / "manufactured-domain-score.json"
    dump(score, {"engineering_fixture": True, "not_actual_qualification": True})
    gate = dict(schema="f3.nopen.domain_gate.v1", stage="domain", status="passed",
                production_resolution_m=.01, time_window_s=[0., 8.35], scoring_interval_s=.01,
                evidence_sha256={data._relative(score): data.sha256(score)})
    dump(out / data.development.MANIFEST, manifest)
    dump(out / data.development.DOMAIN_GATE, gate)
    evidence = [{"path": data._relative(out / name), "sha256": data.sha256(out / name)}
                for name in (data.development.MANIFEST, data.development.DOMAIN_GATE)]
    registry = dict(cases=rows, evidence=evidence,
                    initial_source={"prefix": data._relative(initial),
                                    "assets": {p.name: data.sha256(p) for p in initial.parent.iterdir()}})
    dump(out / data.development.REGISTRY, registry)
    calls = dict(context=0, cases=[])

    def context(*, register):
        assert register is False
        calls["context"] += 1
        for relative, digest in gate["evidence_sha256"].items():
            if data.sha256(data._path(relative)) != digest:
                raise ValueError("manufactured domain evidence changed")
        return dict(gate=gate, manifest=manifest, registry=registry, nominal=nominal)

    def verified(name, shared):
        assert shared["manifest"] is manifest
        calls["cases"].append(name)
        r, a, s = [json.loads((out / f"{name}-{suffix}.json").read_text()) for suffix in ("PREPARED", "AUDIT", "SOLVER")]
        if (a["audit_status"] != "pass_diagnostic" or a["issues"] or a["unknowns"]
                or data.sha256(data._path(a["hdf5"])) != a["hdf5_sha256"]
                or s["status"] != "completed" or s["source_record"] != r):
            raise ValueError("manufactured source hard audit failed")
        return r, a, s

    monkeypatch.setattr(data.development, "_context", context)
    monkeypatch.setattr(data.development, "_verified_development", verified)
    return dict(out=out, rows=rows, calls=calls, source_values=source_values, grid=grid,
                native_times=native_times, ids=ids, masses=masses, p0=p0, slopes=slopes,
                native_velocity=native_velocity, gate=gate, score=score)


@pytest.fixture
def contract(manufactured):
    data.publish_development_contract("pilot")
    return manufactured["out"] / data.CONTRACTS["pilot"]


@pytest.fixture
def core_interface(monkeypatch):
    # These engineering tests exercise the data boundary without a model/GPU.
    @dataclass(frozen=True)
    class Transition:
        case_id: str
        frame: int
        target_indices: tuple | None = None

    @dataclass(frozen=True)
    class TransitionBatch:
        position: object
        velocity: object
        particle_id: object
        target_displacement: object
        time_s: float
        interval_s: float
        dp_m: float
        amplitude: float
        control: object

    module = types.ModuleType("scripts.f3_training_core")
    module.Transition, module.TransitionBatch = Transition, TransitionBatch
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module


def test_pilot_contract_uses_all_original_actual_pilots_once(manufactured):
    value = data.publish_development_contract("pilot")
    expected = [r for r in manufactured["rows"] if r["pilot"]]
    assert manufactured["calls"] == {"context": 1, "cases": [r["case_id"] for r in expected]}
    assert value["completed_case_ids"] == [r["case_id"] for r in expected]
    assert value["qualified_sources"] is True and value["model_qualified"] is False
    assert value["material_layers_qualified"] == [] and value["formal_release"] is False
    assert value["canonical_frame_count"] == 836 and value["time_window_s"] == [0., 8.35]
    for row, saved in zip(expected, value["cases"]):
        assert all(saved[key] == item for key, item in row.items())
        assert saved["hard_audit_passed"] is True
        assert set(saved["sources"]) == {"prepared", "audit", "solver", "input_preflight", "control",
                                         "registered_control", "hdf5", "native_log", "native_timestep"}
        for item in saved["sources"].values():
            assert value["evidence_sha256"][item["path"]] == item["sha256"]
    assert expected[0]["drive_amplitude"] != round(expected[0]["drive_amplitude"], 6)
    assert "later than the target" in value["time_alignment"]


@pytest.mark.parametrize("scope", ["pilot", "full"])
def test_failed_actual_member_cannot_be_replaced_by_other_completed_runs(manufactured, scope):
    row = next(r for r in manufactured["rows"] if r["pilot"] == (scope == "pilot"))
    path = manufactured["out"] / (row["case_id"] + "-AUDIT.json")
    value = json.loads(path.read_text())
    value.update(audit_status="quality_failed", issues=["lost original identity"])
    dump(path, value)
    with pytest.raises(ValueError, match="hard audit"):
        data.publish_development_contract(scope)
    assert not (manufactured["out"] / data.CONTRACTS[scope]).exists()


def test_full_contract_requires_32_distinct_actual_cases_and_keeps_roles(manufactured):
    value = data.publish_development_contract("full")
    assert len(value["completed_case_ids"]) == 32
    assert manufactured["calls"]["context"] == 1 and len(manufactured["calls"]["cases"]) == 32
    assert [sum(c["split"] == split for c in value["cases"]) for split in ("train", "validation", "test")] == [16, 4, 12]


@pytest.mark.parametrize("change", ["completed", "role", "amplitude", "lineage", "qualified", "evidence", "scope"])
def test_contract_flags_and_relabelled_sources_cannot_replace_verification(manufactured, contract, change):
    value = json.loads(contract.read_text())
    if change == "completed":
        value["completed_case_ids"] = value["completed_case_ids"][:-1]
    elif change == "role":
        value["cases"][0]["split"] = "train"
    elif change == "amplitude":
        value["cases"][0]["drive_amplitude"] = round(value["cases"][0]["drive_amplitude"], 6)
    elif change == "lineage":
        value["cases"][0]["physical_lineage_sha256"] = value["cases"][1]["physical_lineage_sha256"]
    elif change == "qualified":
        value["model_qualified"] = True
    elif change == "evidence":
        value["evidence_sha256"].pop(value["cases"][0]["sources"]["control"]["path"])
    else:
        value["scope"] = "full"
    dump(contract, value)
    with pytest.raises(ValueError, match="contract differs"):
        data.validate_development_contract(contract)


@pytest.mark.parametrize("source", ["prepared", "audit", "solver", "input_preflight", "hdf5", "control", "native_log", "native_timestep"])
def test_changed_bound_source_bytes_are_refused(manufactured, contract, source):
    value = json.loads(contract.read_text())
    path = data._path(value["cases"][0]["sources"][source]["path"])
    with path.open("ab") as stream:
        stream.write(b" \n")
    with pytest.raises(ValueError):
        data.validate_development_contract(contract)


def test_readonly_validation_shares_context_and_existing_publish_is_immutable(manufactured, contract):
    before = {p: p.read_bytes() for p in manufactured["out"].glob("*.json")}
    manufactured["calls"].update(context=0, cases=[])
    validated = data.validate_development_contract(contract)
    assert manufactured["calls"]["context"] == 1 and len(manufactured["calls"]["cases"]) == 8
    assert data.publish_development_contract("pilot") == validated
    assert {p: p.read_bytes() for p in manufactured["out"].glob("*.json")} == before


def test_production_defaults_reject_missing_real_domain_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "LAB", tmp_path)
    monkeypatch.setattr(data, "OUT", tmp_path)
    monkeypatch.setattr(data.development, "LAB", tmp_path)
    monkeypatch.setattr(data.development, "OUT", tmp_path)
    with pytest.raises((FileNotFoundError, ValueError)):
        data.publish_development_contract("pilot")
    with pytest.raises((FileNotFoundError, ValueError)):
        data.QualifiedF3Loader()
    assert list(tmp_path.iterdir()) == []


def test_canonical_current_input_and_separate_target_preserve_complete_axes(manufactured, contract):
    with data.QualifiedF3Loader(contract) as loader:
        name = loader.case_ids("train")[0]
        current = loader.current_input(name, 0)
        reference = loader._reference
        assert reference.frame_loads == 1 and list(reference.cache) == [0]
        assert "target_displacement" not in current
        np.testing.assert_array_equal(current["particle_id"], manufactured["ids"])
        np.testing.assert_allclose(current["position"], manufactured["p0"], rtol=0, atol=0)
        np.testing.assert_allclose(current["velocity"], manufactured["native_velocity"], rtol=0, atol=0)
        target = loader.target_displacement(name, 0)
        assert reference.frame_loads == 2
        canonical = reference.canonical_state(1)
        assert canonical["native_bracket_s"][1] > .01
        expected = manufactured["slopes"] * .01 + .001 * .01 * manufactured["native_times"][1]
        np.testing.assert_allclose(target, expected, rtol=0, atol=1e-15)
        later = loader.current_input(name, 1)
        np.testing.assert_allclose(later["velocity"], target / .01, rtol=0, atol=1e-15)
        assert not np.allclose(later["velocity"], manufactured["native_velocity"])
        current["position"][0, 0] = 999
        assert reference.canonical_state(0)["position"][0, 0] != 999
        assert later["interval_s"] == .01


def test_core_callable_catalog_and_heldout_optimization_rejection(manufactured, contract, core_interface):
    with data.QualifiedF3Loader(contract) as loader:
        transitions = loader.optimization_transitions(frames=[0, 834], target_indices=[2, 0])
        assert len(transitions) == 8
        assert all(item.case_id in loader.case_ids("train") for item in transitions)
        batch = loader(transitions[0])
        assert isinstance(batch, core_interface.TransitionBatch)
        assert batch.position.shape == batch.target_displacement.shape == (4, 3)
        np.testing.assert_array_equal(batch.particle_id, manufactured["ids"])
        for split in ("validation", "test"):
            name = loader.case_ids(split)[0]
            with pytest.raises(ValueError, match="original split"):
                loader.optimization_transitions(case_ids=[name])
            with pytest.raises(ValueError, match="cannot enter optimization"):
                loader(core_interface.Transition(name, 0))
            with pytest.raises(ValueError, match="cannot enter optimization"):
                loader.current_input(name, 0)
            evaluation = loader.evaluation_transitions(split, frames=[0])
            assert loader.evaluation_batch(evaluation[0]).position.shape == (4, 3)
        last = loader(transitions[1])
        assert last.time_s == loader.times[834] and loader.times[-1] == 8.35


@pytest.mark.parametrize("frame", [-1, 835, 836, .5, True])
def test_no_extrapolated_or_invalid_transition_indices(manufactured, contract, frame):
    with data.QualifiedF3Loader(contract) as loader:
        with pytest.raises(ValueError, match="transition needs"):
            loader.current_input(loader.case_ids("train")[0], frame)


def test_bounded_cache_and_detached_rollout_reads_only_native_initial(manufactured, contract, monkeypatch):
    with data.QualifiedF3Loader(contract) as loader:
        name = loader.case_ids("train")[0]
        for index in (0, 1, 2, 15, 200, 834):
            loader.current_input(name, index)
            loader.target_displacement(name, index)
            assert len(loader._reference.cache) <= 2 and len(loader._reference.canonical) <= 2
        old = loader._reference
        original = data._Reference.frame
        reads = []

        def track(self, index):
            reads.append(index)
            return original(self, index)

        monkeypatch.setattr(data._Reference, "frame", track)
        initial = loader.rollout_initial(loader.case_ids("test")[0])
        assert set(reads) == {0}
        assert loader._reference is None and not old.h5.id.valid
        assert set(initial) == {"position", "velocity", "particle_id", "mass", "time_s", "interval_s", "dp_m", "amplitude", "control"}
        np.testing.assert_array_equal(initial["mass"], manufactured["masses"])
        np.testing.assert_array_equal(initial["velocity"], manufactured["native_velocity"])


@pytest.mark.parametrize("field", ["valid", "type", "mass", "position"])
def test_no_survivor_filter_or_changed_mass_even_with_mock_passing_audit(manufactured, field):
    row = next(r for r in manufactured["rows"] if r["pilot"] and r["split"] == "train")
    audit_path = manufactured["out"] / (row["case_id"] + "-AUDIT.json")
    audit = json.loads(audit_path.read_text())
    path = data._path(audit["hdf5"])
    with h5py.File(path, "r+") as h:
        if field == "position":
            h[field][2, 0, 0] = np.nan
        else:
            h[field][2, 0] = {"valid": False, "type": 2, "mass": 7.}[field]
    audit["hdf5_sha256"] = data.sha256(path)
    dump(audit_path, audit)
    # Only the manufactured external hard guard is mocked. Each frame still has
    # to preserve all IDs/masses before the unchanged interpolation helper runs.
    data.publish_development_contract("pilot")
    with data.QualifiedF3Loader(manufactured["out"] / data.CONTRACTS["pilot"]) as loader:
        with pytest.raises(ValueError, match="filtering is forbidden|identity mass changed"):
            loader.current_input(row["case_id"], 2)


def test_changed_source_after_loader_initialization_is_rejected(manufactured, contract):
    with data.QualifiedF3Loader(contract) as loader:
        name = loader.case_ids("train")[0]
        path = loader._sources[name]["control_path"]
        path.write_bytes(path.read_bytes() + b"# changed\n")
        with pytest.raises(ValueError, match="changed after"):
            loader.current_input(name, 0)


def test_real_training_core_dataclass_interface_without_model_execution(manufactured, contract):
    from scripts.f3_training_core import Transition, TransitionBatch

    with data.QualifiedF3Loader(contract) as loader:
        transition = loader.optimization_transitions(frames=[0], target_indices=[2, 0])[0]
        assert isinstance(transition, Transition)
        batch = loader(transition)
        assert isinstance(batch, TransitionBatch)
        assert batch.particle_id.dtype == np.int64 and batch.position.shape == (4, 3)
        assert batch.control.at(8.35)[0].shape == (3,)
        assert not batch.control.values.flags.writeable
