from pathlib import Path
import sys,json,runpy
m=runpy.run_path(sys.argv[1])
b=json.loads(Path(sys.argv[2]).read_text())
r=m['_verify_bound_metadata'](b)
Path(sys.argv[3]).write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({'actual_original138_metadata_gate':'pass','case_id':r['case_id'],'native_saved_states':r['full_native_solver']['saved_state_count'],'scientific_payload_IO':False}))
