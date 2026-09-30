from __future__ import annotations

import json
import os
import stat
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.ds_data02_direct_convert import (
    DirectConversionError,
    _assign_types,
    _reject_dynamic_contract,
    compare_reference_hdf5,
    convert_direct,
    eos_pressure,
    parse_particle_blocks,
    raw_tree_manifest,
)


def _write_generated_xml(path: Path, *, dynamic_tag: str | None = None) -> None:
    extra = f"<{dynamic_tag}/>" if dynamic_tag else ""
    path.write_text(
        textwrap.dedent(
            f"""\
            <case>
              <casedef><constantsdef><gravity x="0" y="0" z="-9.81"/></constantsdef>
                <geometry><definition dp="0.1" units_comment="metres (m)"/></geometry>
              </casedef>
              <execution>
                <parameters><parameter key="TimeOut" value="0.1"/></parameters>
                <particles np="4" nb="3">
                  <fixed mkbound="0" mk="10" begin="0" count="1"/>
                  <moving mkbound="1" mk="11" begin="1" count="1"/>
                  <floating mkbound="2" mk="12" begin="2" count="1"/>
                  <fluid mkfluid="0" mk="1" begin="3" count="1"/>
                </particles>
                <constants><data2d value="false"/><gamma value="7"/></constants>
                <motion/>{extra}
              </execution>
            </case>
            """
        ).lstrip(),
        encoding="utf-8",
    )


def _write_fake_decoder(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            #!/usr/bin/env python3
            import pathlib, struct, sys, xml.etree.ElementTree as ET
            import numpy as np
            source, prefix = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
            frame = int(source.stem.split("_")[-1])
            data = prefix / "Frame"
            data.mkdir(parents=True)
            root = ET.Element("root")
            outer = ET.SubElement(root, "item")
            for tag, name, value in [
                ("int", "Npiece", "1"), ("int", "Piece", "0"),
                ("int", "NpDynamic", "0"), ("int", "ReuseIds", "0"),
                ("int", "PeriMode", "0"), ("int", "CaseNp", "4"),
                ("double", "MassBound", "0.002"), ("double", "MassFluid", "0.003"),
                ("double", "B", "162565.71875"), ("double", "Rhop0", "1000"),
                ("double", "Gamma", "7"), ("double", "Dp", "0.1"),
            ]:
                ET.SubElement(outer, tag, name=name, v=value)
            node = ET.SubElement(outer, "item", name="Frame")
            ET.SubElement(node, "double", name="TimeStep", v=str(frame * 0.1))
            root_xml = prefix.with_suffix(".xml")
            ET.ElementTree(root).write(root_xml, encoding="utf-8", xml_declaration=True)
            ids = np.arange(4, dtype=np.uint32)
            pos = np.arange(12, dtype=np.float32).reshape(4, 3) + frame
            vel = np.full((4, 3), frame + 1, dtype=np.float32)
            rho = np.asarray([1000, 1001, 1002, 1003], dtype=np.float32) + frame
            if (source.parent / "drop_frame_zero").exists() and frame == 0:
                keep = np.asarray([0, 1, 3])
                ids, pos, vel, rho = ids[keep], pos[keep], vel[keep], rho[keep]
            ids.tofile(data / "Idp.bin")
            pos.tofile(data / "Pos.bin")
            vel.tofile(data / "Vel.bin")
            rho.tofile(data / "Rhop.bin")
            """,
        ).lstrip(),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_provenance(tmp_path: Path) -> dict[str, Path]:
    data_root = tmp_path / "data"
    data_root.mkdir()
    for frame in range(2):
        (data_root / f"Part_{frame:04d}.bi4").write_bytes(f"frame-{frame}".encode())
    xml = tmp_path / "case.xml"
    _write_generated_xml(xml)
    decoder = tmp_path / "decoder.py"
    _write_fake_decoder(decoder)
    solver_log = tmp_path / "Run.out"
    solver_log.write_text("**3D-Simulation parameters:\n", encoding="utf-8")
    solver_receipt = tmp_path / "solver.json"
    solver_receipt.write_text(json.dumps({"status": "completed", "request": {"command": ["solver"]}}), encoding="utf-8")
    gencase_receipt = tmp_path / "gencase.json"
    gencase_receipt.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    owner = tmp_path / "owner.json"
    owner.write_text(json.dumps({"family_id": "F-test", "physical_case_id": "P-test", "geometry": {"id": "g"}, "control_family_id": "c", "resolution": "test"}), encoding="utf-8")
    return {"data": data_root, "xml": xml, "decoder": decoder, "solver_log": solver_log, "solver_receipt": solver_receipt, "gencase_receipt": gencase_receipt, "owner": owner}


def test_typed_ranges_preserve_all_four_particle_families() -> None:
    blocks = {"np": 4, "blocks": [
        {"type": 0, "mk": 10, "begin": 0, "count": 1},
        {"type": 1, "mk": 11, "begin": 1, "count": 1},
        {"type": 2, "mk": 12, "begin": 2, "count": 1},
        {"type": 3, "mk": 1, "begin": 3, "count": 1},
    ]}
    types, mks = _assign_types(np.arange(4, dtype=np.uint32), blocks)
    assert types.tolist() == [0, 1, 2, 3]
    assert mks.tolist() == [10, 11, 12, 1]


def test_direct_conversion_is_streaming_and_keeps_typed_identity_axis(tmp_path: Path) -> None:
    source = _write_provenance(tmp_path)
    output = tmp_path / "trajectory.h5"
    report_path = tmp_path / "report.json"
    report = convert_direct(
        data_root=source["data"],
        generated_xml=source["xml"],
        output=output,
        report_path=report_path,
        decoder=source["decoder"],
        solver_log=source["solver_log"],
        solver_receipt=source["solver_receipt"],
        gencase_receipt=source["gencase_receipt"],
        owner_metadata=source["owner"],
        run_partvtk=False,
    )
    with h5py.File(output, "r") as h5:
        assert bool(h5.attrs["conversion_complete"]) is True
        assert h5["particle_id"][...].tolist() == [0, 1, 2, 3]
        assert h5["particle_zone"][...].tolist() == [0, 0, 0, 0]
        assert h5["initial_type"][...].tolist() == [0, 1, 2, 3]
        assert h5["initial_mk"][...].tolist() == [10, 11, 12, 1]
        assert h5["valid"].shape == (2, 4)
        assert h5["time"][...].tolist() == pytest.approx([0.0, 0.1])
        assert float(h5["mass"][0, 0]) == pytest.approx(0.002)
        assert float(h5["mass"][0, 3]) == pytest.approx(0.003)
        assert h5.attrs["q_n_status"] == "not_assessed"
    assert report["q_i_status"] == "not_granted; conversion evidence only"
    assert report["partvtk_validation"]["all_passed"] is None
    assert json.loads(report_path.read_text())["source_provenance"]["raw_tree"]["unchanged"] is True


def test_open_or_mult_piece_sources_are_rejected(tmp_path: Path) -> None:
    source = _write_provenance(tmp_path)
    root = ET.parse(source["xml"]).getroot()
    ET.SubElement(root.find(".//execution"), "inout")
    root.find(".//particles").set("np", "4")
    ET.ElementTree(root).write(source["xml"], encoding="utf-8")
    with pytest.raises(DirectConversionError, match="unsupported"):
        # The decoder metadata is closed; the XML tag alone must fail.
        _reject_dynamic_contract(source["xml"], {"Npiece": 1, "Piece": 0, "NpDynamic": 0, "ReuseIds": 0, "PeriMode": 0})


def test_raw_manifest_rejects_frame_gap(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "Part_0000.bi4").write_bytes(b"0")
    (data / "Part_0002.bi4").write_bytes(b"2")
    with pytest.raises(DirectConversionError, match="contiguous"):
        raw_tree_manifest(data)


def test_pressure_uses_native_eos_constants() -> None:
    pressure = eos_pressure(np.asarray([1000.0, 1001.0], dtype=np.float32), {"B": 100.0, "Rhop0": 1000.0, "Gamma": 2.0})
    assert pressure[0] == pytest.approx(0.0)
    assert pressure[1] == pytest.approx(0.2001, rel=1e-4)


def test_finite_initial_exclusion_keeps_full_typed_axis_and_valid_mask(tmp_path: Path) -> None:
    source = _write_provenance(tmp_path)
    (source["data"] / "drop_frame_zero").write_text("type-2 initial cohort intentionally absent\n", encoding="utf-8")
    output = tmp_path / "excluded.h5"
    report = convert_direct(
        data_root=source["data"],
        generated_xml=source["xml"],
        output=output,
        report_path=tmp_path / "excluded-report.json",
        decoder=source["decoder"],
        solver_log=source["solver_log"],
        solver_receipt=source["solver_receipt"],
        gencase_receipt=source["gencase_receipt"],
        owner_metadata=source["owner"],
        run_partvtk=False,
    )
    with h5py.File(output, "r") as h5:
        assert h5["particle_id"][...].tolist() == [0, 1, 2, 3]
        assert h5["initial_type"][...].tolist() == [0, 1, 2, 3]
        assert h5["valid"][0].tolist() == [True, True, False, True]
        ledger = json.loads(h5.attrs["initial_exclusion_ledger_json"])
        assert ledger["count"] == 1
        assert ledger["type_counts"] == {"0": 0, "1": 0, "2": 1, "3": 0}
    assert report["typed_identity"]["initial_exclusion_ledger"]["count"] == 1
