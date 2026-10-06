#!/usr/bin/env python3
import hashlib,json
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]
TAGS=["M085_T080","M085_T090","M085_T100","M085_T120","M095_T080","M095_T090","M095_T100","M095_T120","M105_T080","M105_T090","M105_T100","M105_T120","M115_T080","M115_T090","M115_T100","M115_T120"]
ENDPOINTS=["M085_T080","M115_T100"]
def load(p): return json.loads(p.read_text(encoding="utf-8"))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def req(v,m):
    if not v: raise AssertionError(m)
def main():
    s=load(PKG/"metadata/fresh126-forcing-window-scope.json")
    req(s["candidate_count"]==16 and s["candidate_tags"]==TAGS,"inventory")
    req(s["unique_physical_case_count"]==16 and s["duplicate_physical_case_ids"]==[],"unique physical IDs")
    req(all("A080" not in x and "A120" not in x for x in s["candidate_physical_ids"]),"duplicate endpoint IDs")
    req(s["forcing_complete_within_16s_count"]==12 and s["forcing_truncated_by_16s_count"]==4,"window counts")
    req(s["forcing_truncated_by_16s_tags"]==["M085_T120","M095_T120","M105_T120","M115_T120"],"T120 set")
    req(s["eligible_after_two_endpoint_chains_count"]==10,"eligible count")
    req(s["endpoint_tags"]==ENDPOINTS and s["execution_allowed"] is False,"gate")
    for row in s["rows"]:
        x=load(Path(row["source_request"]))
        req(row["source_request_sha256"]==sha(Path(row["source_request"])),row["tag"]+" source hash")
        req(x["disabled"] is True and x["execution_allowed"] is False,row["tag"]+" disabled")
        req(row["forcing_end_s"]==x["motion_end_s"],row["tag"]+" forcing")
        req(row["physical_case_id"]==x["physical_case_id"],row["tag"]+" physical binding")
    for p in PKG.rglob("*"):
        if p.is_file(): req(p.suffix.lower() not in {".bi4",".h5",".csv",".dat",".vtk",".vtu",".xmf",".xdmf"},"science payload")
    man=load(PKG/"manifest.json")
    for rel,expected in man["files"].items(): req(sha(PKG/rel)==expected,"manifest "+rel)
    report={"schema":"ds02.f5.c082s1.fresh126-validator-report.v1","status":"pass","candidate_count":16,"forcing_complete_within_16s":12,"forcing_truncated_T120":4,"eligible_nonT120_after_endpoints":10,"unique_physical_ids":16,"execution_allowed":False,"science_payloads_read_or_hashed":False}
    (PKG/"metadata/fresh126-validator-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
