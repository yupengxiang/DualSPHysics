from pathlib import Path
import hashlib
import importlib.util

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ds_data02_f1_normal_plane_repair.py"
SPEC = importlib.util.spec_from_file_location("f1_normal_plane_repair", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _source() -> bytes:
    return (
        b'<case><geometry><list name="GeometryForNormals">\n'
        b'<drawbox><point x="0"/><endpoint x="3.23"/><layers vdp="-0.5" /></drawbox>\n'
        b'<drawbox><point x="1.25"/><endpoint x="2.05"/><layers vdp="0.5" /></drawbox>\n'
        b'</list><mainlist><drawbox><layers vdp="0,1,2" /></drawbox>'
        b'<drawbox><layers vdp="0,-1,-2" /></drawbox></mainlist></geometry>'
        b'<normals><norgeometry><distanceh v="3.0" /><svshapes v="true" /></norgeometry></normals></case>'
    )


def test_prepare_changes_only_two_normal_layer_offsets(tmp_path: Path) -> None:
    source = tmp_path / "source.xml"
    output = tmp_path / "candidate.xml"
    source.write_bytes(_source())
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = MODULE.prepare_definition(source, output)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert output.read_bytes().count(b'<layers vdp="0" />') == 2
    assert output.read_bytes().count(b'<layers vdp="0,1,2" />') == 1
    assert output.read_bytes().count(b'<layers vdp="0,-1,-2" />') == 1
    assert result["physical_drawbox_bounds_unchanged"] is True
    assert result["source_unchanged"] is True


def test_prepare_rejects_missing_phase_tokens(tmp_path: Path) -> None:
    source = tmp_path / "source.xml"
    source.write_bytes(_source().replace(b'vdp="0.5"', b'vdp="0"', 1))
    with pytest.raises(ValueError, match="exactly one"):
        MODULE.prepare_definition(source, tmp_path / "candidate.xml")


def test_prepare_refuses_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.xml"
    output = tmp_path / "candidate.xml"
    source.write_bytes(_source())
    output.write_text("immutable")
    with pytest.raises(FileExistsError):
        MODULE.prepare_definition(source, output)
