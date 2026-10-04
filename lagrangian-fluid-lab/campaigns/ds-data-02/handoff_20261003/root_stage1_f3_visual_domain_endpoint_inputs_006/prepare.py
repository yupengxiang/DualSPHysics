"""Prepare two genuine physical forcing endpoints, reusing exact initial BI4.

The immutable baseline XML, geometry, initial fluid, EOS and numerical recipe
are unchanged. New transverse forcing is evaluated by the frozen transformer.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    b = json.loads(args.binding.read_text())
    for name in ('baseline_native_receipt', 'baseline_typed_receipt', 'baseline_gencase_receipt'):
        receipt = json.loads(Path(b[name]).read_text())
        assert (receipt['status'], receipt['returncode']) == ('completed', 0)
    assert not args.output_dir.exists()
    args.output_dir.mkdir(parents=True)
    prefix = Path(b['baseline_prefix'])
    xml, bi4 = prefix.with_suffix('.xml'), prefix.with_suffix('.bi4')
    xsha, bsha = sha(xml), sha(bi4)
    assert xsha == b['baseline_xml_sha256'] and bsha == b['baseline_bi4_sha256']
    root = ET.parse(xml).getroot()
    assert root.find('./execution/constants/data2d').get('value') == 'false'
    particles = {kind: sum(int(x.get('count')) for x in root.findall('./execution/particles/' + kind))
                 for kind in ('fixed', 'moving', 'floating', 'fluid')}
    assert sum(particles.values()) == 179208 and particles['fluid'] == 67500
    spec = importlib.util.spec_from_file_location('frozen_forcing', b['forcing_transformer'])
    forcing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(forcing)
    cases = []
    for candidate in b['candidates']:
        target = args.output_dir / candidate['role'] / candidate['case_id']
        target.parent.mkdir()
        shutil.copyfile(xml, target.with_suffix('.xml'))
        shutil.copyfile(bi4, target.with_suffix('.bi4'))
        assert sha(target.with_suffix('.xml')) == xsha
        assert sha(target.with_suffix('.bi4')) == bsha
        actual_forcing = target.parent / 'CaseSloshingAccData.csv'
        transformed = forcing.transform_twoaxis_forcing_file(
            Path(b['nominal_source_forcing']), actual_forcing,
            amplitude_x=1.0, amplitude_y=candidate['transverse_amplitude_m_s2'],
            omega_y=forcing.DEFAULT_OMEGA_Y, phase_y=0.0, tau_ramp=0.5,
            expected_source_hash=b['nominal_source_forcing_sha256'])
        assert transformed['rows_processed'] == 167001
        assert transformed['source_sha256_before'] == transformed['source_sha256_after']
        physical = copy.deepcopy(b['baseline_physical_binding'])
        physical['physical_case_id'] = candidate['physical_case_id']
        physical['parameters'].update(
            transverse_amplitude_m_s2=candidate['transverse_amplitude_m_s2'],
            reference_variant=candidate['physical_case_id'],
            actual_forcing_sha256=sha(actual_forcing))
        condition = hashlib.sha256(json.dumps(physical, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        entry = {**candidate, 'prepared_prefix': str(target), 'physical_binding': physical,
                 'physical_condition_sha256': condition, 'forcing_transform': transformed,
                 'forcing_path': str(actual_forcing), 'forcing_sha256': sha(actual_forcing),
                 'xml_sha256': xsha, 'bi4_sha256': bsha,
                 'xml_byte_identical_to_baseline': True, 'initial_bi4_byte_identical_to_baseline': True,
                 'initial_native_reference': b['baseline_initial_reference'],
                 'generated_particle_counts': particles,
                 'stage1_visual_status': 'pending full solver/state/ParaView/visual review',
                 'numerical_precision_status': 'not accepted',
                 'physical_window_s': [0, 8.35], 'save_interval_s': 0.01,
                 'expected_frames': 836, 'production_approval': 'none',
                 'independent_case_increment': 0}
        (target.parent / 'prepared-input-report.json').write_text(json.dumps(entry, indent=2) + '\n')
        cases.append(entry)
    assert sha(xml) == xsha and sha(bi4) == bsha
    report = {'schema': 'ds02.stage1.f3.physical-visual-endpoints-inputs.v1',
              'cases': cases, 'original_geometry_initial_eos_recipe_unchanged': True,
              'varied_physical_parameter': 'transverse linear acceleration amplitude',
              'meaning': 'New physical controls, not discretization reruns. Count only after complete product and visual acceptance.',
              'precision_qualification': 'not granted', 'production_approval': 'none'}
    (args.output_dir / 'prepared-cases.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'prepared_physical_endpoint_inputs': len(cases), 'accepted_cases': 0}), flush=True)


if __name__ == '__main__':
    main()
