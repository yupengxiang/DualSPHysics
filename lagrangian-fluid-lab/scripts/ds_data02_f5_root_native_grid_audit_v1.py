"""Independently verify immutable F5 double-precision initial native fluid grids."""
import argparse,importlib.util,json,os,sys
from pathlib import Path
import numpy as np
from ds_data02_native_labels import digest

def audit(metadata,prefix,output):
    if output.exists():raise FileExistsError(output)
    lab=Path(__file__).resolve().parents[1]
    helper=lab/'campaigns/ds-data-02/families/F2/f2_handoff_20261002_native_mass_audit.py'
    decoder=lab/'scripts/f8_r008_safe_bi4_decoder_v1.py'
    spec=importlib.util.spec_from_file_location('f5_root_readonly_native',helper)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    scanner=module._load_safe_decoder(decoder)
    m=json.loads(metadata.read_text());native=prefix.with_suffix('.bi4');receipt=prefix.parent/'execution-receipt.json'
    sources=[metadata,native,prefix.with_suffix('.xml'),receipt,helper,decoder,Path(__file__).resolve()]
    for key in ['repair_definition','repair_motion','repair_bed']:
        p=Path(m[key]['path']);assert digest(p)==m[key]['sha256'];sources.append(p)
    hashes={str(p):digest(p) for p in sources}
    fd=os.open(native,os.O_RDONLY)
    try:scan=scanner.scan_bi4_fd(fd,hashes[str(native)])
    finally:os.close(fd)
    values={v.name:v.value for v in scan.root.values};arrays={a.name:a for a in scan.arrays if a.item_path[-1]==scan.root.children[0].name}
    assert arrays['Posd'].type_code==23
    pos=np.memmap(native,mode='r',dtype='<f8',offset=arrays['Posd'].offset,shape=(arrays['Posd'].count,3))
    ids=np.memmap(native,mode='r',dtype='<u4',offset=arrays['Idp'].offset,shape=(arrays['Idp'].count,))
    total,fluid,fixed,moving=[int(values[k]) for k in ['CaseNp','CaseNfluid','CaseNfixed','CaseNmoving']]
    fp=pos[ids>=total-fluid];l=m['lattice'];dp=float(l['dp_m']);first=np.array(l['first_center_m']);counts=np.array(l['counts_xyz']);index=np.rint((fp-first)/dp).astype(np.int64)
    residual=float(np.abs(fp-(first+index*dp)).max());low=np.array(m['physical_contract']['continuum_low_m']);high=np.array(m['physical_contract']['continuum_high_m'])
    in_grid=np.all((index>=0)&(index<counts));flat=(index[:,0]*counts[1]+index[:,1])*counts[2]+index[:,2]
    launch=json.loads(receipt.read_text());mass=fluid*float(values['MassFluid'])
    checks={'completed_gencase':launch['status']=='completed' and launch['returncode']==0,'native_3d':not bool(values.get('Data2d',False)),'all_native_ids_once':np.array_equal(np.sort(ids),np.arange(total)),'all_initial_positions_finite':bool(np.isfinite(pos).all()),'partition_consistent':total==fluid+fixed+moving,'expected_native_fluid_count':fluid==int(l['particle_count']),'every_fluid_on_cell_center':residual<1e-10,'full_exact_cartesian_grid':bool(in_grid and len(np.unique(flat))==int(np.prod(counts))==fluid),'strict_fluid_physical_bounds':bool(np.all(fp>low) and np.all(fp<high)),'native_unscaled_continuum_mass':bool(np.isclose(mass,m['physical_contract']['continuum_mass_kg'],rtol=1e-12,atol=1e-12)),'source_bytes_unchanged':all(digest(Path(p))==v for p,v in hashes.items())}
    out={'schema':'ds02.f5.root-native-grid-audit.v1','case_id':m['case_id'],'checks':checks,'pass':all(checks.values()),'fluid_particles':fluid,'total_particles':total,'native_massfluid_kg':values['MassFluid'],'initial_fluid_mass_kg':mass,'maximum_double_precision_grid_residual_m':residual,'fluid_bounds_m':[fp.min(axis=0).tolist(),fp.max(axis=0).tolist()],'source_sha256':hashes,'q_n_status':'not_assessed','limitation':'Initial grid and native mass only; finite solid surface coverage and motion domain require separate audit'}
    output.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({k:out[k] for k in ['case_id','pass','fluid_particles','initial_fluid_mass_kg','maximum_double_precision_grid_residual_m']}));return out['pass']
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['metadata','prefix','output']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();sys.exit(0 if audit(a.metadata,a.prefix,a.output) else 1)
