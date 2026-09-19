from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from scripts import l2_f1r_audit as f1r


def _write_definition(path: Path) -> None:
    path.write_text(
        """<case>
  <casedef><constantsdef><cflnumber value=\"0.2\" /></constantsdef>
  <geometry><definition dp=\"0.0075\" /></geometry></casedef>
  <execution><parameters>
    <parameter key=\"SavePosDouble\" value=\"0\" />
    <parameter key=\"TimeOut\" value=\"0.05\" />
    <simulationdomain>
      <posmin x=\"default - 25%\" y=\"default - 25%\" z=\"default - 25%\" />
      <posmax x=\"default + 25%\" y=\"default + 25%\" z=\"default + 75%\" />
    </simulationdomain>
  </parameters></execution>
</case>"""
    )


def _write_generated_definition(path: Path) -> None:
    path.write_text(
        """<case>
  <execution><parameters><simulationdomain>
    <posmin x=\"default - 25%\" y=\"default - 25%\" z=\"default - 25%\" />
    <posmax x=\"default + 25%\" y=\"default + 25%\" z=\"default + 75%\" />
  </simulationdomain></parameters></execution>
  <particles><_summary><positions>
    <posmin x=\"0\" y=\"0\" z=\"0\" />
    <posmax x=\"1.2\" y=\"0.3975\" z=\"0.6\" />
  </positions></_summary></particles>
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


def test_resolve_runtime_domain_uses_generated_particle_envelope(tmp_path: Path):
    path = tmp_path / "generated.xml"
    _write_generated_definition(path)

    result = f1r.resolve_runtime_domain(path)

    assert result is not None
    assert result["zmax"] == 1.05
    assert result["xmin"] == -0.3
    assert result["ymax"] == 0.496875


def test_repairs_are_materialized_without_changing_source(tmp_path: Path):
    source = tmp_path / "source.xml"
    repair = tmp_path / "repair.xml"
    alternative = tmp_path / "alternative.xml"
    _write_definition(source)
    original = source.read_text()

    f1r.apply_runtime_domain_repair(source, repair)
    f1r.apply_time_boundary_alternative(source, alternative)

    assert source.read_text() == original
    repair_root = f1r.ET.parse(repair).getroot()
    assert repair_root.find(".//simulationdomain/posmax").attrib["z"] == "1.35"
    alt_root = f1r.ET.parse(alternative).getroot()
    assert alt_root.find(".//cflnumber").attrib["value"] == "0.05"
    assert alt_root.find(".//parameter[@key='SavePosDouble']").attrib["value"] == "2"
    assert alt_root.find(".//parameter[@key='TimeOut']").attrib["value"] == "0.02"


def test_missing_identity_join_keeps_native_reason_and_runtime_ceiling(tmp_path: Path):
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

    result = f1r._missing_identity_join(
        hdf5,
        native,
        {2: {"part": 2, "time_s": 0.1, "reason_counts": {"position": 1}},},
        {"zmax": 1.05},
    )

    assert result["summary"]["native_join_count"] == 1
    assert result["summary"]["runtime_domain_ceiling_classified_count"] == 1
    assert result["rows"][0]["classification"] == "position_exclusion_at_runtime_domain_upper_face"


def test_background_evidence_marks_missing_reference_as_blocker(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(f1r, "LAB", tmp_path)
    evidence = f1r._background_evidence()

    assert len(evidence) == 2
    assert all(item["reference_status"].startswith("blocked_") for item in evidence)
    assert all(item["blocker"] for item in evidence)


def test_report_writer_keeps_f1r_prefix_and_no_gpu_claim(tmp_path: Path):
    report = {
        "status": "complete_with_findings",
        "new_gpu_jobs": 0,
        "native_failure_evidence": {"identity_join": {"native_join_count": 1, "missing_initial_identity_count": 1, "reason_counts": {"position": 1}, "runtime_domain_ceiling_classified_count": 1}},
        "native_failure_hypotheses": [{"status": "supported_but_unconfirmed", "implemented_repair": {"status": "implemented_not_run"}}],
        "background_reference_evidence": [{"background_id": "plain", "reference_status": "blocked_input_only", "blocker": "missing"}],
        "external_blockers": [{"id": "external", "status": "blocked_external", "requirement": "anchor"}],
    }
    json_path = tmp_path / "l2_f1r_evidence.json"
    md_path = tmp_path / "l2_f1r_evidence.md"

    f1r.write_report(report, json_path=json_path, markdown_path=md_path)

    assert json_path.name.startswith("l2_f1r_")
    assert md_path.name.startswith("l2_f1r_")
    assert json.loads(json_path.read_text())["new_gpu_jobs"] == 0
    assert "blocked_input_only" in md_path.read_text()
