import xml.etree.ElementTree as ET

from scripts import f3_ref0081818_prepare as prepare
from scripts import l1r_branch_runner


def test_manifest_is_preparation_only_and_exactly_tiled():
    manifest = prepare._manifest()
    assert manifest["launch_allowed"] is False
    assert manifest["resource_policy"]["launch_requires_new_authorization"] is True
    assert manifest["exact_tiling"]["fluid_shape"] == [110, 22, 11]
    assert manifest["exact_tiling"]["fluid_particles"] == 26620
    assert abs(manifest["exact_tiling"]["dp_m"] - 0.09 / 11.0) < 1e-15
    assert manifest["new_v2_status"] == "not_scored_preparation_only"
    assert "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen" in manifest["reused_hash_bound_evidence"]


def test_definition_rewrite_preserves_fixed_volume_tiling(tmp_path):
    root = ET.fromstring(
        """<case><casedef><geometry><definition dp=\"0.0075\"><pointref x=\"0\" y=\"0\" z=\"0\"/></definition><commands><mainlist><drawbox><point/><size/></drawbox><drawbox><point/><size/></drawbox></mainlist></commands></geometry></casedef></case>"""
    )
    source = tmp_path / "source.xml"
    target = tmp_path / "target.xml"
    source.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    prepare._rewrite_definition(source, target)
    out = ET.parse(target).getroot()
    definition = out.find("./casedef/geometry/definition")
    assert abs(float(definition.get("dp")) - prepare.DP) < 1e-15
    fluid, bound = out.findall("./casedef/geometry/commands/mainlist/drawbox")
    assert abs(float(fluid.find("./size").get("x")) - (0.9 - prepare.DP)) < 1e-15
    assert abs(float(bound.find("./size").get("z")) - (0.51 + prepare.DP)) < 1e-15


def test_shared_runner_rejects_prepared_only_recipe_without_authorization_file():
    try:
        l1r_branch_runner.run({
            "recipe_id": prepare.RECIPE,
            "id": "R0081818-NOMINAL",
            "case_id": "R0081818-NOMINAL",
        })
    except PermissionError as error:
        assert "authorization" in str(error)
    else:  # pragma: no cover - the guard must be the first executable branch
        raise AssertionError("prepared-only ref0081818 record reached the runner")
