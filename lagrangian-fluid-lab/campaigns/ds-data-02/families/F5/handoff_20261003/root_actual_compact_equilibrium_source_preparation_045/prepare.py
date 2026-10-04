import argparse,json,hashlib,sys,importlib.util,shutil,collections,math
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--binding',required=True);p.add_argument('--output-dir',required=True);a=p.parse_args();b=json.loads(Path(a.binding).read_text());out=Path(a.output_dir);out.mkdir(exist_ok=False)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
modules={}
for row in b['selected_modules']:
 path=Path(row['path']);assert sha(path)==row['sha256'];spec=importlib.util.spec_from_file_location(path.stem,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);modules[path.stem]=m
bed=modules['generate_compact_continuous_bed_stl'];motion=modules['generate_compact_packet_motion'];tri=bed.build_compact_bed_triangles();edges=collections.Counter()
for t in tri:
 assert len(set(t))==3
 for i in range(3):edges[tuple(sorted([t[i],t[(i+1)%3]]))]+=1
assert all(v==2 for v in edges.values());assets=out/'assets';assets.mkdir();stl=assets/'f5_compact_continuous_bed_profile.stl';dat=assets/'f5_compact_packet_motion.dat'
with stl.open('x') as f:f.write(bed.generate_stl_ascii_text())
table=motion.generate_motion_table();assert len(table)==641 and table[0]==(0.,0.) and table[-1]==(16.,0.) and all(math.isfinite(x) for row in table for x in row) and all(table[i][0]<table[i+1][0] for i in range(len(table)-1));assert max(abs(x) for t,x in table)<=.03
with dat.open('x') as f:f.write(motion.format_motion_dat_17g(table))
rows=[]
for row in b['definitions']:
 src=Path(row['definition']);assert sha(src)==row['definition_sha256'];target=out/(row['case_id']+'_Def.xml')
 with target.open('xb') as f:f.write(src.read_bytes())
 rows.append({**row,'prepared_definition':str(target),'assets':[{'relative_name':'assets/'+q.name,'source':str(q),'sha256':sha(q),'bytes':q.stat().st_size} for q in [stl,dat]]})
report={'schema':'ds02.root.actual-compact-equilibrium-source-preparation.v1','cases':rows,'motion_rows':len(table),'motion_window_s':[0,16],'motion_format':'17g','bed_facets':len(tri),'mesh_all_edges_twice':True,'continuum_mass_kg':{'runup':bed.CONTINUUM_RUNUP_MASS_KG,'weir':bed.CONTINUUM_WEIR_MASS_KG},'native_state':'pending actualGenCase andinitialarrays','q_n':'not_granted','production_approval':'none','independent_case_count_increment':0,'limitations':b['limitations']}
with (out/'prepared-source-report.json').open('x') as f:json.dump(report,f,indent=2);f.write('\n')
print(json.dumps({'prepared_cases':len(rows),'bed_facets':len(tri),'motion_rows':len(table)}))
