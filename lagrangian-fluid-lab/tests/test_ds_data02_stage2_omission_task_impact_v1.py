import hashlib
import json
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import ds_data02_stage2_omission_task_impact_v1 as impact


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sidecar(tmp_path, xml):
    rows = [
        dict(zone=0, idp=100, initial_mass_kg=0.001,
             first_missing_frame=4, first_missing_bracket_s=[0.3, 0.4],
             native_motive='position', native_exit_cause='NUMERICAL_POSITION_EXCLUSION'),
        dict(zone=0, idp=102, initial_mass_kg=0.001,
             first_missing_frame=5, first_missing_bracket_s=[0.4, 0.5],
             native_motive='position', native_exit_cause='NUMERICAL_POSITION_EXCLUSION'),
    ]
    path = tmp_path / 'join.json'
    path.write_text(json.dumps({
        'schema': 'ds02.stage2.omission-forensics.v2',
        'status': 'CAUSES_RECONCILED', 'family_id': 'F2',
        'physical_case_id': 'synthetic',
        'physical_fate': 'UNKNOWN', 'dynamical_impact': 'NOT_ASSESSED',
        'typed_identity': {'missing_fluid_count': len(rows)},
        'source_provenance': {'generated_xml': {'path': str(xml), 'sha256': digest(xml)}},
        'excluded_particles': rows,
    }))
    return path


def test_task_screen_uses_frozen_xml_mk_ranges_and_keeps_unknown(tmp_path):
    xml = tmp_path / 'case.xml'
    xml.write_text('''<case><massfluid value="0.001"/><particles>
      <fluid count="4"><fluid mkfluid="0" mk="10" begin="100" count="2"/>
      <fluid mkfluid="1" mk="11" begin="102" count="2"/></fluid>
    </particles></case>''')
    result = impact.assess(sidecar(tmp_path, xml))
    assert result['frozen_initial_fluid_mass']['initial_fluid_mass_kg'] == 0.004
    assert result['missing_mass_screen']['identified_missing_mass_fraction'] == pytest.approx(0.5)
    assert result['missing_mass_screen']['screen'] == 'EXCEEDS_REGISTERED_WIDTH_SCREEN'
    assert [(row['mk'], row['missing_count']) for row in result['source_mk_breakdown']] == [(10, 1), (11, 1)]
    assert result['unknown_and_acceptance']['dynamical_impact'] == 'NOT_ASSESSED'
    assert result['source_evidence']['trajectory_h5_read'] is False


def test_task_screen_rejects_changed_xml(tmp_path):
    xml = tmp_path / 'case.xml'
    xml.write_text('<case><massfluid value="0.001"/><particles><fluid count="1"/></particles></case>')
    path = sidecar(tmp_path, xml)
    xml.write_text(xml.read_text() + ' ') 
    with pytest.raises(impact.EvidenceError, match='digest changed'):
        impact.assess(path)
