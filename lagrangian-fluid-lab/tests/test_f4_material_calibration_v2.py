from scripts.core_material import GATE
from scripts.f4_material_calibration_v2 import SCHEMA, design, run


def test_v2_calibration_is_held_out_and_gate_fixed():
    record = design()
    assert record['schema'] == SCHEMA
    assert record['qualification_claim'] == 'none'
    assert record['geometry']['q_cases'] == [0.25, 0.75]
    assert {row['id'] for row in record['manufactured_fields']} == {
        'constant_offset', 'cubic_shear', 'vortex_interface',
    }
    for candidate in record['backend_candidates'].values():
        assert candidate['gate'] == dict(GATE)
    receipt = run(record)
    assert receipt['qualification_claim'] == 'none'
    assert receipt['all_mass_closure_pass'] is True
    assert receipt['source_macro_budget_pass_by_variant'] == {
        'baseline24': False,
        'f4_affine_bound_v2': False,
        'f4_ess32_v2': True,
    }
