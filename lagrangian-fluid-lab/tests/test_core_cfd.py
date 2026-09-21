import json
from pathlib import Path

import pytest

from scripts.core_cfd import (RESOLUTIONS, f4_config, lattice_box, make_job,
                              mass_quality, qualification_design,
                              validate_prepared_matrix)
from scripts.core_runtime import digest


def _prepared_record(config):
    boxes = []
    for item in (config["pool"], config["drop"]):
        box = lattice_box(item["low"], item["size"], config["dp_m"])
        box["mkfluid"] = item["mkfluid"]
        boxes.append(box)
    sampling = {
        "fluid_boxes": boxes,
        "expected_fluid_particles": sum(x["particle_count"] for x in boxes),
        "mass_policy": "native rho*dp^3, no mass rescaling; continuous-volume representation error explicit",
    }
    return {
        "schema": "core.cfd.v1",
        "config": config,
        "sampling": sampling,
        "native_initial": {
            "fluid_particles": sampling["expected_fluid_particles"],
            "initial_state_pass": True,
        },
        "preflight_pass": True,
        "solver_binary": "",
        "qualification_claim": "none; preparation only",
    }


def _write_synthetic_matrix(root):
    design = qualification_design()
    (root / "design.json").write_text(json.dumps(design))
    rows = []
    for index, config in enumerate(design["cells"]):
        path = root / f"cell-{index:02d}" / "prepared.json"
        path.parent.mkdir()
        path.write_text(json.dumps(_prepared_record(config)))
        rows.append({"index": index, "case_id": config["case_id"],
                     "prepared": str(path), "preflight_pass": True})
    (root / "prepared-matrix.json").write_text(json.dumps({
        "schema": "core.cfd.v1", "design_sha256": digest(root / "design.json"),
        "cells": rows, "complete": True, "qualification_claim": "none",
    }))


def test_mass_gate_rejects_legacy_coarse_sampling_and_accepts_revision():
    legacy = lattice_box([.08, .04, .04], [1.04, .32, .14], .09 / 11)
    legacy_drop = lattice_box([.25, .12, .4], [.26, .16, .14], .09 / 11)
    assert not mass_quality({"fluid_boxes": [legacy, legacy_drop]})["mass_gate_pass"]
    revision = [lattice_box([.08, .04, .04], [1.04, .32, .14], dp)
                for dp in (.01, .0075, .005)]
    for box in revision:
        assert mass_quality({"fluid_boxes": [box]})["mass_gate_pass"]


def test_qualification_design_is_frozen_13_plus_2_full_window():
    design = qualification_design()
    assert len(design["cells"]) == 15
    assert design["registered_window"]["initial_time_max_s"] == pytest.approx(4.34)
    assert design["qualification_claim"] == "none"
    assert design["mass_policy"].startswith("native rho*dp^3")
    spatial = [x for x in design["cells"] if x["design_cell"] == "spatial"]
    assert len(spatial) == 13
    assert {x["dp_m"] for x in spatial if x["parameter"]["q"] == .5} == set(RESOLUTIONS)


def test_prepared_revision_passes_static_matrix_validation(tmp_path):
    root = tmp_path / "matrix"
    root.mkdir()
    _write_synthetic_matrix(root)
    report = validate_prepared_matrix(root)
    assert report["static_quality_pass"]
    assert report["cell_count"] == 15
    assert report["spatial_cell_count"] == 13
    assert report["temporal_cell_count"] == 2


def test_static_matrix_rejects_changed_continuum(tmp_path):
    root = tmp_path / "matrix"
    root.mkdir()
    _write_synthetic_matrix(root)
    path = root / "cell-00" / "prepared.json"
    record = json.loads(path.read_text())
    record["config"]["drop"]["size"][0] = .27
    path.write_text(json.dumps(record))
    report = validate_prepared_matrix(root)
    assert not report["static_quality_pass"]
    assert any("continuum pool/drop geometry changed" in issue for issue in report["issues"])


def test_canary_job_has_runtime_contract_and_hashed_inputs(tmp_path):
    lab = tmp_path / "lab"
    (lab / "scripts").mkdir(parents=True)
    solver = tmp_path / "solver"
    solver.write_bytes(b"solver")
    config = f4_config(.005, 1., stage="canary")
    prepared = _prepared_record(config)
    prepared["solver_binary"] = str(solver)
    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_text(json.dumps(prepared))
    output = tmp_path / "job.json"
    spec = make_job(prepared_path, lab, output, job_id="f4-test-canary")
    assert spec["argv"][-1] == "{attempt_dir}/product"
    assert spec["resources"] == {"cpu_cores": 2, "ram_mib": 16384,
                                  "gpu_peak_mib": 4096, "io_weight": 1}
    assert spec["required_outputs"][-1] == "product/observations.json"
    assert spec["input_files"][0]["sha256"] == digest(prepared_path)
    assert json.loads(output.read_text())["job_id"] == "f4-test-canary"


def test_explicit_physical_viscosity_has_units_and_distinct_formulation(tmp_path):
    import xml.etree.ElementTree as ET
    from scripts.core_cfd import definition
    lab = Path(__file__).resolve().parents[1]
    template = lab/'campaigns/l1-resume/artifacts/f3-revision075/F3_REV075_R075-ENDPOINT-LOW-0075/F3_CELL3_plain_0p0075_Def.xml'
    config = f4_config(.0075, 1., stage='canary')
    baseline = tmp_path/'baseline.xml'; definition(config, template, baseline)
    assert ET.parse(baseline).find(".//parameter[@key='ViscoTreatment']").get('value') == '1'
    config.update(physical_kinematic_viscosity_m2_s=1e-6, viscosity_formulation='laminar')
    target = tmp_path/'laminar.xml'; definition(config, template, target)
    root = ET.parse(target)
    assert root.find(".//parameter[@key='ViscoTreatment']").get('value') == '3'
    assert float(root.find(".//parameter[@key='Visco']").get('value')) == 1e-6
    config['physical_kinematic_viscosity_m2_s'] = float('nan')
    with pytest.raises(ValueError, match='finite and positive'):
        definition(config, template, target)
