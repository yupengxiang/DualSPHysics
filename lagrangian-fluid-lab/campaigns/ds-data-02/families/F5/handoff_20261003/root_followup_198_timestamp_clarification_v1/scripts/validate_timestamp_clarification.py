#!/usr/bin/env python3
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
def main():
 m=json.loads((ROOT/"manifest.json").read_text()); assert m["manifest_excludes_self"] and m["source_only"]
 for e in m["files"]:
  p=ROOT/e["path"]; assert p.is_file() and p.stat().st_size==e["bytes"] and hashlib.sha256(p.read_bytes()).hexdigest()==e["sha256"]
 d=json.loads((ROOT/"metadata/timestamp-clarification.json").read_text())
 assert d["interpretation"]["original_reviewed_at_is_authoritative"] is False
 assert d["interpretation"]["personal_visual_review_completed"] is True
 assert d["source_agent_boundary"]["raw_h5_bi4_csv_dat_vtk_read_or_hashed"] is False
 print("fresh198 timestamp clarification validation PASS")
if __name__=="__main__": main()
