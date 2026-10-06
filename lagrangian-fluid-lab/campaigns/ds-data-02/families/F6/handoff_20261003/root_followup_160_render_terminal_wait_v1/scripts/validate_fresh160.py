#!/usr/bin/env python3
import json,hashlib
from pathlib import Path
P=Path(__file__).resolve().parents[1]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 d=json.load(open(P/"metadata/render-terminal-wait.json")); assert d["selection"]["visual_review_started"] is False; assert d["selection"]["case_credit"]==0
 assert d["source_boundary"]["science_arrays_opened"] is False and d["source_boundary"]["png_opened"] is False and d["source_boundary"]["science_jobs_started"] is False
 for key in ("root951_controller","root1067_controller"):
  q=d[key]; lp=Path(q["launch_process"]["path"]); rp=Path(q["target"]["request"]); assert lp.is_file() and rp.is_file(); assert sha(lp)==q["launch_process"]["sha256"]; assert sha(rp)==q["target"]["request_sha256"]; assert q["terminal_artifact"] is None
 print("fresh160 wait validator: PASS; visual_review=0; case_credit=0; terminal_artifacts=0")
if __name__=="__main__": main()
