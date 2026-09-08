from pathlib import Path

from scripts import r6_n3_followup as n3


def test_n3_is_two_case_single_factor_cfl_probe():
    cases = n3.records()
    assert len(cases) == 2
    assert {case["height_label"] for case in cases} == {"h09", "h11"}
    assert all(case["resolution"] == "fine" for case in cases)
    assert all(case["cfl_number"] == 0.1 for case in cases)
    assert all(case["registered_absorbing_exit_faces"] == [] for case in cases)


def test_parse_domain_prefers_gencase_resolved_particle_envelope(tmp_path: Path):
    path = tmp_path / "generated.xml"
    path.write_text(
        "<root><execution><parameters><simulationdomain>"
        '<posmin x="default - 25%" y="default - 25%" z="default - 25%"/>'
        '<posmax x="default + 25%" y="default + 25%" z="default + 75%"/>'
        "</simulationdomain></parameters></execution>"
        "<particles><_summary><positions>"
        '<posmin x="0.006" y="0.006" z="0.006"/>'
        '<posmax x="1.196" y="0.398" z="0.594"/>'
        "</positions></_summary></particles></root>"
    )
    assert n3._parse_domain(path) == {
        "min_m": [0.006, 0.006, 0.006],
        "max_m": [1.196, 0.398, 0.594],
    }
