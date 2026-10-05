from pathlib import Path
import argparse,json,hashlib
p=argparse.ArgumentParser();p.add_argument('--binding',required=True);p.add_argument('--output',required=True);a=p.parse_args()
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
b=json.loads(Path(a.binding).read_text());rows=[]
for row in b['rows']:
 rp=Path(row['producer_receipt']);assert sha(rp)==row['producer_receipt_sha256'];r=json.loads(rp.read_text());assert r['status']=='completed' and r['returncode']==0
 q=json.loads(Path(row['source_request']).read_text());assert sha(row['source_request'])==row['source_request_sha256']
 for inp,h in r['input_hashes_at_launch'].items():assert sha(inp)==h,(inp,'producer input mutation')
 before={k:sha(row[k]) for k in ['xml','bi4']};assert all(Path(row[k]).stat().st_size>0 for k in before)
 after={k:sha(row[k]) for k in before};assert before==after
 rows.append({**row,'generated_xml_sha256':before['xml'],'generated_bi4_sha256':before['bi4'],'producer_completed_0':True,'source_input_hashes_preserved':True})
Path(a.output).write_text(json.dumps({'schema':'ds02.actual-generated-payload-hash-audit.v1','cases':rows,'pass':True,'independent_case_increment':0},indent=2)+'\n')
