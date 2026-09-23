from __future__ import annotations

import xml.etree.ElementTree as ET

from scripts import f8_r008_definition_control_pack_v1 as pack
from scripts import f8_t1_scope_design_v1 as scope


def test_all_rendered_definitions_include_the_frozen_f8_constants():
    expected_constants = {
        "gravity",
        "rhop0",
        "rhopgradient",
        "hswl",
        "gamma",
        "speedsystem",
        "coefsound",
        "speedsound",
        "coefh",
        "cflnumber",
    }
    rows = scope.qualification_matrix() + scope.production_manifest()
    assert len(rows) == 47

    for row in rows:
        control_name = f"F8_OPC_{row['case_id']}_acceleration.csv"
        root = ET.fromstring(pack.render_definition(row, control_name))
        constants = root.find("./casedef/constantsdef")
        assert constants is not None
        present_constants = {child.tag for child in constants}
        assert expected_constants <= present_constants, row["case_id"]
