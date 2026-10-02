from __future__ import annotations

from pathlib import Path

from scripts.ds_data02_f3_quarter_dt_prepare import prepare


def test_prepare_changes_only_registered_dt_parameters(tmp_path: Path) -> None:
    source_xml = tmp_path / "source.xml"
    source_bi4 = tmp_path / "source.bi4"
    source_control = tmp_path / "F3_DualAxisPhase_WeakControl.csv"
    source_control.write_bytes(b"frozen-control")
    # Patch the module constant for a synthetic source so the test exercises
    # semantics without depending on the real external control file.
    import scripts.ds_data02_f3_quarter_dt_prepare as module
    module.CONTROL_SHA = module.sha256(source_control)
    source_xml.write_text('''<case><execution><parameters>
<parameter key="DtIni" value="0.1"/><parameter key="DtMin" value="0.2"/>
<parameter key="DtFixed" value="0.3"/><parameter key="DtFixedFile" value="NONE"/>
<parameter key="TimeOut" value="0.0025"/><parameter key="TimeMax" value="10"/>
</parameters></execution></case>''')
    source_bi4.write_bytes(b"bi4")
    report_path = tmp_path / "attempt" / "prepared-report.json"
    report = prepare(source_xml=source_xml, source_bi4=source_bi4,
                     source_control=source_control, output_dir=report_path.parent / "prepared",
                     output_report=report_path, case_id="F3_QUARTER")
    assert report["co_location"]["xml_bi4_same_directory"]
    assert report["co_location"]["xml_control_same_directory"]
    assert report["numeric_parameters"]["changed_keys"] == ["DtIni", "DtMin", "DtFixed"]
    assert report["numeric_parameters"]["patched"]["DtFixedFile"] == "NONE"
    assert (report_path.parent / "prepared" / "F3_QUARTER.bi4").read_bytes() == b"bi4"
