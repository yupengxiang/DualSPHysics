from pathlib import Path
import sys,json,runpy
m=runpy.run_path(sys.argv[1])
b=m['validate_binding'](Path(sys.argv[2]))
o=m['_load_original']()
m['_bind_original_case_id'](o,b)
r=o._verify_bound_metadata(b)
Path(sys.argv[3]).write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({'real_original_metadata_gate':'pass','case_id':r['case_id'],'scientific_payload_IO':False}))
