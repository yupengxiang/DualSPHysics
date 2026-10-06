from pathlib import Path
import argparse,json,runpy,sys
p=argparse.ArgumentParser();p.add_argument('--worker',type=Path,required=True);p.add_argument('--request',type=Path,required=True);a=p.parse_args()
q=json.loads(a.request.read_text());library=runpy.run_path(str(a.worker));result=library['execute_request'](q,authorized=True)
summary={k:result.get(k) for k in ['status','reason','returncode','published_output_root','published_bytes','post_publish_home_floor_rechecked']}
print(json.dumps(summary),flush=True)
# A library rejection is a failed registered task, not a completed renderer.
raise SystemExit(0 if result.get('status')=='completed' and result.get('post_publish_home_floor_rechecked') is True else 1)
