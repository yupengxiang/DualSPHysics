"""Bind one concrete root-reviewed request to the immutable M4 batch admission."""
import argparse,json,sys
from pathlib import Path
P=Path(__file__).resolve().parents[1];ROOT=P.parents[3]
sys.path.insert(0,str(ROOT/'lagrangian-fluid-lab/scripts'))
import ds_data02_runtime_v6_batch2 as b

def grant(request_path):
 request=Path(request_path).resolve();admission=P/'batch2-runtime/root-batch-2-admission.json'
 a=b.validate_admission(admission,data_root=b.DATA_ROOT);r=json.loads(request.read_text())
 target=P/'batch2-runtime/grants'/f"{r['case_id']}-{r['attempt_id']}.json"
 target.parent.mkdir(parents=True,exist_ok=True);assert not target.exists()
 d={'schema':b.GRANT_SCHEMA,'status':'granted','issuer':'root','immutable':True,'batch_index':2,'admission_path':str(admission),'admission_payload_sha256':a['payload_sha256'],'request_path':str(request),'request_sha256':b._sha256_file(request),'attempt_id':f"{r['family_id']}/{r['case_id']}/{r['attempt_id']}"}
 d['payload_sha256']=b._payload_hash(d)
 with target.open('x') as f:json.dump(d,f,indent=2);f.write('\n')
 b._validate_request_binding(request,r,grant_path=target,admission_path=admission,admission=a)
 return target
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('request',type=Path);args=p.parse_args();print(grant(args.request))
