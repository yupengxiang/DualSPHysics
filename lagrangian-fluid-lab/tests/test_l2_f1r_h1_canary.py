from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

import h5py
import numpy as np

from scripts import l2_f1r_audit as f1r
from scripts import l2_f1r_h1_canary as h1


def _write_definition(path: Path) -> None:
    path.write_text(
        """<case>
  <casedef><constantsdef><gravity x="0" y="0" z="-9.81" /><cflnumber value="0.2" /></constantsdef>
    <geometry><definition dp="0.0075"><commands><mainlist><drawbox><point x="0" y="0" z="0" /><size x="1" y="1" z="1" /></drawbox></mainlist></commands></definition></geometry>
  </casedef>
  <execution><parameters>
    <parameter key="SavePosDouble" value="2" /><parameter key="TimeMax" value="0.6" /><parameter key="TimeOut" value="0.02" />
    <simulationdomain><posmin x="default - 25%" y="default - 25%" z="default - 25%" /><posmax x="default + 25%" y="default + 25%" z="default + 75%" /></simulationdomain>
  </parameters></execution>
</case>"""
    )


def _write_hdf5(path: Path) -> None:
    with h5py.File(path, "w") as handle:
        handle["time"] = np.asarray([0.0, 0.1, 0.2])
        handle["particle_id"] = np.asarray([10, 11], dtype=np.int64)
        handle["valid"] = np.asarray([[True, True], [True, False], [True, False]])
        handle["position"] = np.asarray(
            [
                [[0.1, 0.1, 0.1], [0.2, 0.1, 0.1]],
                [[0.1, 0.1, 0.2], [np.nan, np.nan, np.nan]],
                [[0.1, 0.1, 0.3], [np.nan, np.nan, np.nan]],
            ],
            dtype=np.float64,
        )
        handle["velocity"] = np.zeros((3, 2, 3), dtype=np.float64)
        handle["mass"] = np.ones((3, 2), dtype=np.float64)
        handle["density"] = np.full((3, 2), 1000.0, dtype=np.float64)
        handle["type"] = np.full((3, 2), 3, dtype=np.int8)
        handle["mk"] = np.ones((3, 2), dtype=np.int8)
        handle.attrs["lifecycle_model"] = "closed"


def test_materialize_definition_changes_only_explicit_domain(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.xml"
    destination = tmp_path / "h1.xml"
    _write_definition(source)
    monkeypatch.setattr(h1.f1r, "F1_DEFINITION", source)

    original = source.read_text()
    h1.materialize_definition(destination)

    assert source.read_text() == original
    domain = ET.parse(destination).getroot().find(".//simulationdomain")
    assert domain is not None
    assert domain.find("posmax").attrib["z"] == "1.35"
    assert h1._canonical_without_runtime_domain(source) == h1._canonical_without_runtime_domain(destination)


def test_recipe_contract_records_baseline_and_h1_hashes(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.xml"
    h1_definition = tmp_path / "h1.xml"
    generated = tmp_path / "generated.xml"
    _write_definition(source)
    monkeypatch.setattr(h1.f1r, "F1_DEFINITION", source)
    h1.materialize_definition(h1_definition)
    generated.write_text(h1_definition.read_text())
    monkeypatch.setattr(h1.f1r, "F1_GENERATED_XML", generated)
    monkeypatch.setattr(h1, "H1_DEFINITION", h1_definition)

    contract = h1.recipe_contract()

    assert contract["baseline_definition_sha256"]
    assert contract["baseline_generated_xml_sha256"]
    assert contract["h1_required_zmax_m"] == 1.35
    assert contract["same_non_domain_recipe"] is True


def test_gpu_isolation_binds_physical_gpu_to_logical_zero(monkeypatch):
    record = {"index": 7, "uuid": "GPU-test", "memory_used_mib": 15, "utilization_percent": 0}
    monkeypatch.setattr(h1.c1, "inventory_allowlist", lambda: ["GPU-test"])
    monkeypatch.setattr(h1.c1, "require_idle_allowed_gpu", lambda index, allowed: record)
    result = h1.gpu_preflight(7)

    assert result["physical_gpu_index"] == 7
    assert result["cuda_visible_devices"] == "7"
    assert result["solver_gpu_argument"] == 0
    assert result["single_device_namespace"] is True


def test_identity_join_keeps_runparts_partout_and_hdf5_counts(tmp_path: Path):
    hdf5 = tmp_path / "case.h5"
    _write_hdf5(hdf5)
    native = [
        {
            "particle_id": 11,
            "part_out": 2,
            "motive": 1,
            "position_m": [0.2, 0.1, 1.0517],
            "velocity_m_s": [0.0, 0.0, 1.0],
            "density_kg_m3": 1000.0,
            "native_reason": "position",
        }
    ]
    runparts = {2: {"part": 2, "time_s": 0.1, "reason_counts": {"position": 1}}}

    joined = f1r._missing_identity_join(hdf5, native, runparts, {"zmax": 1.05})
    snapshot = h1._after_snapshot(
        {"attempt_id": "test", "attempt_directory": str(tmp_path)},
        hdf5,
        {"zmax": 1.05},
        {"status": "available", "rows": native, "reason_counts": {"position": 1}},
        runparts,
        joined,
        {"structural_pass": True},
    )

    assert snapshot["runparts"]["reason_counts"]["position"] == 1
    assert snapshot["partout"]["reason_counts"]["position"] == 1
    assert snapshot["identity_join"]["summary"]["native_join_count"] == 1
    assert snapshot["position_exclusion"]["hdf5_identity_join"] == 1


def test_position_comparison_reports_h1_removal():
    before = {"position_exclusion": {key: 85 for key in (
        "runparts", "partout", "hdf5_identity_join", "hdf5_missing_initial_identity", "hdf5_native_join", "runtime_domain_ceiling_classified"
    )}}
    after = {"position_exclusion": {key: 0 for key in before["position_exclusion"]}}

    result = h1.compare_position_exclusions(before, after)

    assert result["position_exclusion_removed"] is True
    assert result["delta_after_minus_before"]["partout"] == -85


def test_report_contract_prohibits_shared_state_and_receipt(tmp_path: Path):
    report_path = tmp_path / "h1-report.json"
    report = {
        "schema": "l2r.f1r.h1.canary.v1",
        "shared_resume_state_updated": False,
        "receipt_emitted": False,
        "qualification_claim": "none",
    }
    h1._write_report(report, report_path)
    loaded = json.loads(report_path.read_text())

    assert loaded["shared_resume_state_updated"] is False
    assert loaded["receipt_emitted"] is False
    assert loaded["qualification_claim"] == "none"
