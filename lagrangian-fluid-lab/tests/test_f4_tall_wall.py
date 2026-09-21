import xml.etree.ElementTree as ET
import pytest
from scripts.core_cfd import definition, f4_config


def test_tall_wall_geometry_and_normals_share_height(tmp_path):
    template = tmp_path / 'template.xml'
    template.write_text('<case><casedef><constantsdef><cflnumber value=".05"/></constantsdef><geometry><definition/><commands/></geometry></casedef><execution><parameters/></execution></case>')
    cfg = f4_config()
    cfg['container_height_m'] = 1.2
    cfg['wall_bounds'] = dict(cfg['wall_bounds'], zmax=1.2)
    target = tmp_path / 'case.xml'
    definition(cfg, template, target)
    root = ET.parse(target).getroot()
    boxes = root.findall('.//drawbox')
    closed = [box for box in boxes if box.find('boxfill').text == 'all^top']
    assert len(closed) == 2
    assert float(closed[0].find('size').get('z')) == 1.2
    assert float(closed[1].find('point').get('z')) + float(closed[1].find('size').get('z')) == pytest.approx(1.2)
    cfg['wall_bounds']['zmax'] = .6
    with pytest.raises(ValueError, match='audit wall bounds'):
        definition(cfg, template, target)
