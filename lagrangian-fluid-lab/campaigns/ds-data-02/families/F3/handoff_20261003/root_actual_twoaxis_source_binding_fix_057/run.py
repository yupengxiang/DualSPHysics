"""Same exact plain geometry, independent transverse acceleration mechanism."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import selected_owner_transformer as forcing

def digest(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as stream:
        while chunk := stream.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()

def semantic(node):
    return (node.tag, sorted((k,v) for k,v in node.attrib.items() if not k.endswith('comment')),
            (node.text or '').strip(), [semantic(child) for child in node])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    b = json.loads(args.binding.read_text())
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    receipt = json.loads(Path(b['source_gencase_receipt']).read_text())
    if receipt['status'] != 'completed' or receipt['returncode'] != 0:
        raise ValueError('Completed original GenCase required')
    original = Path(b['original_definition'])
    generated = Path(b['original_generated_xml'])
    definition_tree = ET.parse(original).getroot()
    if semantic(definition_tree.find('casedef')) != semantic(ET.parse(generated).find('casedef')):
        raise ValueError('Whole original casedef differs from actual GenCase')
    args.output_dir.mkdir()
    target_definition = args.output_dir / (b['case_id']+'_Def.xml')
    with original.open('rb') as source, target_definition.open('xb') as target:
        shutil.copyfileobj(source,target)
    if digest(target_definition) != digest(original):
        raise ValueError('Original complete definition bytes differ')
    # Frequency is a physical scale choice, not a claim of native resonance truth.
    frequency = forcing.DEFAULT_OMEGA_Y
    target_forcing = args.output_dir / 'CaseSloshingAccData.csv'
    report = forcing.transform_twoaxis_forcing_file(Path(b['source_forcing']), target_forcing,
              amplitude_x=1.0, amplitude_y=b['transverse_amplitude_m_s2'], omega_y=frequency,
              phase_y=0.0, tau_ramp=.5, expected_source_hash=b['source_forcing_sha256'])
    if report['rows_processed'] != 167001 or report['source_sha256_before'] != report['source_sha256_after']:
        raise ValueError('Full original source/time grid missing')
    prefix = args.output_dir / b['case_id']
    command = [b['gen_binary'], str(target_definition.with_suffix('')), str(prefix), '-save:all', '-threads:1']
    run = subprocess.run(command,capture_output=True,text=True)
    # Preserve official stdout for the shared runner's independent count parser.
    sys.stdout.write(run.stdout)
    sys.stderr.write(run.stderr)
    if run.returncode:
        raise RuntimeError('Actual official GenCase failed')
    actual = ET.parse(prefix.with_suffix('.xml')).getroot()
    if semantic(actual.find('casedef')) != semantic(definition_tree.find('casedef')):
        raise ValueError('New GenCase changed original full casedef')
    constants = {node.tag:dict(node.attrib) for node in actual.find('./execution/constants')}
    if constants['data2d']['value'] != 'false' or float(constants['dp']['value']) != b['dp_m']:
        raise ValueError('Actual 3D discretization differs')
    counts = {key:sum(int(node.get('count')) for node in actual.findall('./execution/particles/'+key))
              for key in ['fixed','moving','floating','fluid']}
    if counts['fluid'] != b['expected_fluid'] or sum(counts.values()) != b['expected_total']:
        raise ValueError('Actual GenCase particle cohort differs from original mother')
    physical = copy.deepcopy(b['nominal_physical_binding'])
    physical.update(mechanism_id='F3_TWOAXIS_TRANSVERSE_LINACC_V1',
                    physical_case_id='F3_TWOAXIS_AY0P50_PITCH_NOMINAL',
                    paired_background_id='twoaxis_transverse_linear')
    physical['parameters'].update(transverse_amplitude_m_s2=b['transverse_amplitude_m_s2'],
                    transverse_omega_rad_s=frequency, transverse_phase_rad=0.0,
                    transverse_ramp_duration_s=.5, transverse_active_window_s=[0,8.35],
                    drive_amplitude_G=1.0, reference_variant='TWOAXIS_AY0P50',
                    forcing_source_sha256=b['source_forcing_sha256'], actual_forcing_sha256=digest(target_forcing))
    # Physical identity excludes discretization; retain source lineage group to prevent leakage.
    mother = copy.deepcopy(physical)
    mother['parameters'].pop('actual_forcing_sha256')
    mother_sha = hashlib.sha256(json.dumps(mother,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    result = {'schema':'ds02.f3.root-exact-geometry-twoaxis-preparation.v1',
              'case_id':b['case_id'],'prefix':str(prefix),'physical_binding':physical,
              'physical_condition_sha256':mother_sha,'forcing_transform':report,
              'original_definition_sha256':digest(original),'new_definition_sha256':digest(target_definition),
              'source_gencase_receipt':b['source_gencase_receipt'],
              'xml_sha256':digest(prefix.with_suffix('.xml')), 'bi4_sha256':digest(prefix.with_suffix('.bi4')),
              'forcing_sha256':digest(target_forcing),'actual_generated_constants':constants,
              'generated_xml_particle_counts':counts,'whole_original_geometry_definition_exact':True,
              'native_initial_typed_QA':'pending Root actual arrays',
              'actual_second_axis_native_velocity_evidence':'pending actual full native run',
              'q_n':'not_granted','production_approval':'none','independent_case_count_increment':0}
    with (args.output_dir/'prepared-input-report.json').open('x') as stream:
        json.dump(result,stream,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps({'case':b['case_id'],'actual_xml_cohort':counts,'q_n':'not_granted'}))

if __name__ == '__main__':
    main()
