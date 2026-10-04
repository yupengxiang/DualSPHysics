import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ds_data02_stage1_production_f1 as a
for v in ('ecc','dual'):
 p=Path(__file__).resolve().parent/v/'request.json'
 hashes=a.authorize(json.loads(p.read_text()),index_path=Path(__file__).resolve().parent/'proposed-approved-visual-scopes.json')
 print(json.dumps({'variant':v,'authorized_hashes':len(hashes),'solver_launched':False}),flush=True)
