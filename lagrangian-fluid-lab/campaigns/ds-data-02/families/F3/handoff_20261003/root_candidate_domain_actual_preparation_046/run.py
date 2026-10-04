"""Prepare one real registered amplitude case with byte-exact selected owner."""
import argparse,importlib.util,json,hashlib
from pathlib import Path
import xml.etree.ElementTree as E

def sem(n):return(n.tag,sorted((k,v) for k,v in n.attrib.items() if not k.endswith('comment')),(n.text or '').strip(),[sem(c) for c in n])
def main():
 p=argparse.ArgumentParser();p.add_argument('--binding',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();b=json.loads(a.binding.read_text())
 if a.output_dir.exists():raise FileExistsError('Preserve prepared output')
 if b['amplitude'] not in [.9,.97,1.1] or b['dp_m'] not in [.006,.005]:raise ValueError('Unregistered domain')
 if sem(E.parse(b['definition']).getroot())!=sem(E.parse(b['root_nominal_definition']).getroot()):raise ValueError('Whole geometry/recipe changed')
 g=E.parse(b['definition']).find('./casedef/geometry/definition');dp=b['dp_m']
 if float(g.get('dp'))!=dp or any(float(g.find('pointref').get(ax))!=dp/2 for ax in 'xyz'):raise ValueError('Grid differs')
 s=importlib.util.spec_from_file_location('selected_owner',Path(__file__).with_name('owner_prepare_v3.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);r=m.prepare_single_case(b,a.output_dir)
 if r['generated_xml_particle_counts']['fluid']!=b['expected_fluid'] or sum(r['generated_xml_particle_counts'].values())!=b['expected_total']:raise ValueError('Actual GenCase domain population differs from nominal geometry')
 physical=b['physical_binding'];physical['parameters']['drive_amplitude_G']=b['amplitude'];physical['parameters']['acceleration_source_semantics']='Pinned original nominal CSV with full-precision g+A*(a-g), alphaA transform; actual SHA '+r['forcing_sha256']
 canonical=json.dumps(physical,sort_keys=True,separators=(',',':')).encode();proof={'physical_binding':physical,'physical_binding_canonical_sha256':hashlib.sha256(canonical).hexdigest(),'actual_forcing_sha256':r['forcing_sha256'],'amplitude':b['amplitude'],'actual_complete_source_rows':r['forcing_transform_details']['rows_processed'],'definition_whole_nominal_semantics_proved':True,'actual_native_typed_initial_qa':'pending','q_n':'not_granted','production_approval':'none'}
 with (a.output_dir/'root-domain-binding.json').open('x') as f:json.dump(proof,f,indent=2);f.write('\n')
 print(json.dumps({'case':b['case_id'],'gencase_complete':True,'native_initial_QA':'pending'}))
if __name__=='__main__':main()
