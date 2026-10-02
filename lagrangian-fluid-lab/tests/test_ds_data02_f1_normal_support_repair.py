from pathlib import Path
import hashlib
import importlib.util

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ds_data02_f1_normal_support_repair.py"
SPEC = importlib.util.spec_from_file_location("f1_normal_support_repair", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_prepare_changes_only_distanceh_and_preserves_svshapes(tmp_path: Path) -> None:
    source = tmp_path / "source.xml"
    output = tmp_path / "candidate.xml"
    source.write_bytes(
        b'<normals active="true">\n'
        b'  <norgeometry>\n'
        b'    <geometryfile file="[CaseName]_hdp_Actual.vtk" />\n'
        b'    <distanceh v="2.0" />\n'
        b'    <svshapes v="true" />\n'
        b'  </norgeometry>\n'
        b'</normals>\n'
    )
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = MODULE.prepare_definition(source, output)
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert before == after == result["source_sha256"]
    assert output.read_bytes() == source.read_bytes().replace(
        b'<distanceh v="2.0" />', b'<distanceh v="3.0" />'
    )
    assert b'<svshapes v="true" />' in output.read_bytes()
    assert result["source_unchanged"] is True


def test_prepare_rejects_missing_or_ambiguous_delta(tmp_path: Path) -> None:
    source = tmp_path / "source.xml"
    source.write_text('<distanceh v="2.0" />\n<distanceh v="2.0" />\n<svshapes v="true" />\n')
    with pytest.raises(ValueError, match="exactly one"):
        MODULE.prepare_definition(source, tmp_path / "candidate.xml")


def test_prepare_refuses_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.xml"
    output = tmp_path / "candidate.xml"
    source.write_text('<distanceh v="2.0" /><svshapes v="true" />')
    output.write_text("immutable")
    with pytest.raises(FileExistsError):
        MODULE.prepare_definition(source, output)
