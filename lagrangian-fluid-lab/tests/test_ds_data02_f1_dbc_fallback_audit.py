from __future__ import annotations

from pathlib import Path

from scripts.ds_data02_f1_dbc_fallback_audit import _same_except_boundary


def test_boundary_only_byte_delta(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.xml"
    candidate = tmp_path / "candidate.xml"
    baseline.write_bytes(
        b'<case><parameter key="Boundary" value="2" /><parameter key="TimeMax" value="6" /></case>'
    )
    candidate.write_bytes(
        b'<case><parameter key="Boundary" value="1" /><parameter key="TimeMax" value="6" /></case>'
    )
    assert _same_except_boundary(baseline, candidate)


def test_unrelated_xml_change_is_rejected(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.xml"
    candidate = tmp_path / "candidate.xml"
    baseline.write_bytes(
        b'<case><parameter key="Boundary" value="2" /><parameter key="TimeMax" value="6" /></case>'
    )
    candidate.write_bytes(
        b'<case><parameter key="Boundary" value="1" /><parameter key="TimeMax" value="5" /></case>'
    )
    assert not _same_except_boundary(baseline, candidate)
