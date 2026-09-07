from scripts.r3_g2_f2_resolution import records, retry_records
from scripts.w06_rotating_pour import definition_text


def test_f2_primary_matrix_has_three_backgrounds_and_resolutions():
    matrix = records()
    assert len(matrix) == 9
    assert len({item["background"] for item in matrix}) == 3
    assert len({item["dp"] for item in matrix}) == 3
    assert {item["dp"] for item in matrix} == {0.025, 0.018, 0.0145}
    assert all(item["tout"] == 0.01 for item in matrix)


def test_pour_definition_separates_resolution_and_saved_cadence():
    record = records()[0]
    definition = definition_text(record)
    assert f'dp="{record["dp"]}"' in definition
    assert f'key="TimeOut" value="{record["tout"]}"' in definition


def test_mdbc_retry_changes_only_declared_numerical_formulation():
    retry = retry_records()[0]
    definition = definition_text(retry)
    assert 'key="Boundary" value="2"' in definition
    assert '<normals active="true">' in definition
    assert retry["dp"] == 0.0175
    assert retry["tout"] == 0.01
