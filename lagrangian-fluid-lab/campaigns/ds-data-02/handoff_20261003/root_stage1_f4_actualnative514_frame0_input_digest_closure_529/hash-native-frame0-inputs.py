from pathlib import Path
import argparse,json,hashlib
p=argparse.ArgumentParser();p.add_argument('--binding',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();b=json.loads(a.binding.read_text());a.output_dir.mkdir(parents=True,exist_ok=True);out=a.output_dir/'native-frame0-input-digests.json';assert not out.exists();rows=[]
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for z in iter(lambda:f.read(1024*1024),b''):h.update(z)
 return h.hexdigest()
for c in b['cases']:
 r=json.loads(Path(c['native_receipt']).read_text());assert (r['status'],r['returncode'])==('completed',0) and sha(c['native_receipt'])==c['native_receipt_sha256'];rows.append({'case_id':c['case_id'],'native_receipt':c['native_receipt'],'source_binding':c['source_binding'],'input_sha256':{p:sha(p) for p in c['files']}})
out.write_text(json.dumps({'schema':'ds02.root.registered-native-input-closure.v1','actual_cases':24,'cases':rows,'registered_worker_only_scientific_hashing':True,'case_increment':0},indent=2)+'\n');print(json.dumps({'actual_cases':len(rows),'scientific_input_digests':sum(len(x['input_sha256']) for x in rows)}))
