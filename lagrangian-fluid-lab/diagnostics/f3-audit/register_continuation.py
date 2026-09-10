"""Register forcing semantics and CELL3 canary without launching CFD."""
import hashlib
import json
from pathlib import Path
import numpy as np

LAB = Path(__file__).resolve().parents[2]
OUT = LAB / 'campaigns/l1-resume/continuation'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    folder = LAB / 'campaigns/l1-resume/artifacts/cell3/F3_CELL3_plain_0p01'
    drive = folder / 'CaseSloshingAccData.csv'
    a = np.loadtxt(drive, delimiter=';', comments='#')
    assert a.shape[1] == 7 and np.isfinite(a).all()
    assert a[0, 0] == 0 and np.all(np.diff(a[:, 0]) > 0)
    assert a[-1, 0] == 8.35
    source = LAB / 'vendor/official/DualSPHysics_v5.4/src/source'
    protocol = {
        'schema': 'f3.cell3.protocol.v1',
        'status': 'registered_before_CELL3_solver; qualification_pending',
        'coordinate_frame': 'fixed tank computational coordinates, not reconstructed inertial world',
        'forcing': {
            'kind': 'version-specific prescribed body acceleration; no rigid-pose equivalence claimed',
            'centre_m': [0.45, 0, 0], 'globalgravity': False,
            'columns': ['time_s', 'ax', 'ay', 'az', 'alpha_x', 'alpha_y', 'alpha_z'],
            'linear_units': 'm/s^2', 'angular_units': 'rad/s^2',
            'gravity_handling': 'solver subtracts global gravity then adds CSV linear acceleration, which already includes gravity',
            'velocity_integration': 'zero initial velocity; right endpoint sums of acceleration times native CSV dt, then linear interpolation',
            'angular_branch': 'GPU applies angular terms only when instantaneous angular acceleration is nonzero',
            'caution': 'GPU Coriolis implementation is component-specific; do not replace it with an assumed rigid-frame formula',
            'amplitude_definition': 'a_lin = g + amplitude*(a_lin_nominal-g); alpha = amplitude*alpha_nominal; derived velocities use the same native integration',
            'zero_drive': 'linear=(0,0,-9.81), angular=(0,0,0), globalgravity=0',
            'drive_sha256': digest(drive), 'rows': len(a),
            'range_s': [float(a[0, 0]), float(a[-1, 0])],
            'column_min': a[:, 1:].min(axis=0).tolist(),
            'column_max': a[:, 1:].max(axis=0).tolist(),
            'source_hashes': {n: digest(source/n) for n in ['JDsAccInput.cpp','JDsAccInput_ker.cu']},
        },
        'candidate_production_dp_m': 0.01, 'reference_dp_m': [0.01, 0.0075, 0.006],
        'geometry_m': [0.9, 0.18, 0.51], 'water_depth_m': 0.09,
        'target_mass_kg': 14.58,
        'long_window_s': [0, 8.35], 'long_window_basis': 'entire finite prescribed input; periodicity not assumed',
        'canary_window_s': [0, 1.5], 'canary_scope': 'input repair and hard integrity only',
        'output_interval_s': 0.01, 'output_control_interval_s': 0.002,
        'cfl': [0.05, 0.025], 'time_output_error_budget': 0.01,
        'reference_error_budget': 0.05, 'energy_scale': '0.5*M0*9.81*0.09',
        'old_v1': 'preserve registered histograms, outside/missing mass, all 21 historical times and failures',
        'new_v2': 'not designed or accepted; manufactured calibration required before new CFD qualification',
        'control_amplitudes': [0.9, 1.0, 1.1], 'independent_internal_amplitude': 0.97,
        'qualification_attempt_plan': {'repair_canary':1,'time_and_output':3,'long_ladder':3,'endpoints':6,'internal':2},
        'task_scope': {'T1':'numerical particle state in tank coordinates', 'T2':'separate macro and path qualification required'},
        'formal_release': False,
    }
    (OUT/'F3-CELL3-PROTOCOL.json').write_text(json.dumps(protocol, indent=2)+'\n')
    record = json.loads((OUT/'F3_3D_CELL2_plain_dp0p01_INPUTFIX-PREPARED.json').read_text())
    name = 'F3_CELL3_plain_0p01'
    record.update(id=name, case_id=name, phase='F3_CELL3_repair_canary',
                  generated_prefix=str((folder/name).relative_to(LAB)),
                  candidate_definition=str((folder/(name+'_Def.xml')).relative_to(LAB)),
                  generated_xml_sha256=digest(folder/(name+'.xml')),
                  protocol_sha256=digest(OUT/'F3-CELL3-PROTOCOL.json'),
                  gencase={'total_particles':57060,'fluid_particles':14580},
                  repair_of='F3_3D_CELL2_plain_dp0p01_INPUTFIX')
    (OUT/(name+'-PREPARED.json')).write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps({'protocol':'F3-CELL3-PROTOCOL.json','canary':name,'launch':False}))


if __name__ == '__main__':
    main()
