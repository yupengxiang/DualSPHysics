"""Measure union-native finite solids, retaining individual marker bounds and face diagnostics."""
import argparse,importlib.util,json,os,sys
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial import cKDTree
from ds_data02_native_labels import digest
from ds_data02_f7_initial_native_audit_v1 import face_coverage

def audit(request,output):
    if output.exists():raise FileExistsError(output)
    lab=Path(__file__).resolve().parents[1];r=json.loads(request.read_text());prefix=Path(r['input_prefix']);native=prefix.with_suffix('.bi4');generated=prefix.with_suffix('.xml')
    helper=lab/'campaigns/ds-data-02/families/F2/f2_handoff_20261002_native_mass_audit.py';decoder=lab/'scripts/f8_r008_safe_bi4_decoder_v1.py'
    spec=importlib.util.spec_from_file_location('f5_solid_safe_native',helper);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);scanner=m._load_safe_decoder(decoder)
    sources=[request,native,generated,helper,decoder,Path(__file__).resolve(),lab/'scripts/ds_data02_f7_initial_native_audit_v1.py'];hashes={str(p):digest(p) for p in sources}
    fd=os.open(native,os.O_RDONLY)
    try:scan=scanner.scan_bi4_fd(fd,hashes[str(native)])
    finally:os.close(fd)
    a={x.name:x for x in scan.arrays if x.item_path[-1]==scan.root.children[0].name};v={x.name:x.value for x in scan.root.values}
    pos=np.memmap(native,mode='r',dtype='<f8',offset=a['Posd'].offset,shape=(a['Posd'].count,3));ids=np.memmap(native,mode='r',dtype='<u4',offset=a['Idp'].offset,shape=(a['Idp'].count,));root=ET.parse(generated).getroot();blocks={int(x.get('mkbound')):x for x in root.find('.//particles') if x.tag in ['fixed','moving']};dp=float(v['Dp'])
    def cloud(marker):
        b=blocks[marker];lo=int(b.get('begin'));hi=lo+int(b.get('count'));return pos[(ids>=lo)&(ids<hi)]
    geometry=root.find('.//geometry/commands/mainlist');marker=None;faces={};triangles=[];solid=pos[ids<int(v['CaseNp'])-int(v['CaseNfluid'])];marker_bounds={str(k):[cloud(k).min(axis=0).tolist(),cloud(k).max(axis=0).tolist()] for k in blocks}
    for item in geometry:
        if item.tag=='setmkbound':marker=int(item.get('mk'))
        if item.tag=='setmkfluid':break
        if item.tag=='drawbox':
            low=np.array([float(item.find('point').get(k)) for k in ['x','y','z']]);size=np.array([float(item.find('size').get(k)) for k in ['x','y','z']]);fill=item.findtext('boxfill');selected=[(2,0),(2,1)] if fill=='bottom' else [(i,s) for i in range(3) for s in [0,1]]
            faces[item.get('cmt')]=face_coverage(solid,low,low+size,selected,dp)
        if item.tag=='drawfilestl':
            stl=Path(r.get('geometry_asset_root',str(generated.parent)))/item.get('file');sources.append(stl);hashes[str(stl)]=digest(stl);vertices=[]
            for line in stl.read_text().splitlines():
                fields=line.strip().split()
                if fields and fields[0]=='vertex':vertices.append(list(map(float,fields[1:])))
            t=np.array(vertices).reshape(-1,3,3);bary=np.array([[1,0,0],[0,1,0],[0,0,1],[.5,.5,0],[.5,0,.5],[0,.5,.5],[1/3,1/3,1/3],[.5,.25,.25],[.25,.5,.25],[.25,.25,.5]])
            sample=np.einsum('si,tic->tsc',bary,t).reshape(-1,3);d,nearest=cKDTree(solid).query(sample);tol=np.sqrt(3)*dp/2+1e-9;triangles.append({'file':str(stl),'native_marker':marker,'triangles':len(t),'samples_per_triangle':len(bary),'sample_count':len(sample),'geometric_half_cell_diagonal_tolerance_m':float(tol),'maximum_nearest_node_distance_m':float(d.max()),'samples_outside_tolerance':int(np.sum(d>tol)),'all_triangle_samples_covered':bool((d<=tol).all()),'uncovered_samples':[{'triangle_index':int(j//len(bary)),'barycentric_sample_index':int(j%len(bary)),'sample_m':sample[j].tolist(),'nearest_native_solid_node_m':solid[nearest[j]].tolist(),'distance_m':float(d[j]),'native_tolerance_m':float(tol)} for j in np.flatnonzero(d>tol)]})
    checks={'all_declared_drawbox_faces_have_full_tangential_extent':all(x['covered'] for f in faces.values() for x in f.values()),'all_finite_stl_triangle_samples_have_native_nodes':bool(triangles) and all(x['all_triangle_samples_covered'] for x in triangles),'source_bytes_unchanged':all(digest(Path(p))==h for p,h in hashes.items())}
    report={'schema':'ds02.f5.root-union-solid-coverage.v5','case_id':r['case_id'],'checks':checks,'pass':all(checks.values()),'native_marker_bounds_m':marker_bounds,'declared_finite_face_coverage':faces,'stl_triangle_sampling':triangles,'source_sha256':hashes,'q_n_status':'not_assessed','limitations':['Finite sampling of every STL triangle; no continuum face quadrature accuracy claim','Both registered lower and fluid-facing upper floor planes measured separately; union witness avoids lost material interfaces due GenCase overwrite. No assumption equating boxfill bottom with highz; individual marker bounds retained; no moving-piston dynamic pose claim']};output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'pass':report['pass'],'checks':checks,'stl':triangles}));return report['pass']
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();sys.exit(0 if audit(a.request,a.output) else 1)
