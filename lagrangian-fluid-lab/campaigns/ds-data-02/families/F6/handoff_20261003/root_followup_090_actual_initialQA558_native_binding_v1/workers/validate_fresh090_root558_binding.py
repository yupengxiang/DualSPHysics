#!/usr/bin/env python3
"""Validate fresh090 Root558 QA metadata and disabled native bindings.

Only JSON metadata and source request files are read.  This validator never
opens BI4/H5/CSV/DAT/scientific arrays and never launches a process.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any

OLD_MARKERS = ("root146", "root_stage1_f6_first8", "mechanical-pose-omega-initial-native-qa-089")

def sha(p: Path) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def load(p: Path) -> dict[str,Any]:
    d=json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(d,dict): raise RuntimeError(f"expected object: {p}")
    return d

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--package",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    a=ap.parse_args(); pkg=a.package.resolve()
    binding=load(pkg/"qa/initial-native-qa-root558-binding.json")
    assert binding["case_count"]==24
    requests=sorted((pkg/"qualification/requests").glob("*.json"))
    assert len(requests)==24, len(requests)
    rows=[]; seen=set(); completed=pending=failed=0
    for p in requests:
        d=load(p); cid=str(d["case_id"]); assert cid not in seen; seen.add(cid)
        assert d["disabled"] is True and d["launch"] is False
        assert d["launch_allowed"] is False and d["execution_allowed"] is False
        qa=d["actual_initial_qa"]
        assert qa["attempt_id"].endswith("-089-root558")
        assert qa["request"].endswith("root_stage1_f6_actualGen539_corrected_metadata_native_initial_QA_558/"+cid+"-initial-qa-request.json")
        assert qa["binding"].endswith(cid+"-initial-QA-binding.json")
        assert qa["report"] and qa["receipt"] and qa["index"]
        for value in (qa["request"],qa["binding"],qa["worker"]):
            assert Path(value).exists(), value
        for field in ("report_sha256","receipt_sha256","index_sha256"):
            if qa.get(field) is not None: assert len(str(qa[field]))==64
        text=json.dumps(qa,sort_keys=True)
        assert not any(marker in text for marker in OLD_MARKERS)
        if qa.get("pass") is True: completed+=1
        elif qa.get("status")=="root558_failed_or_nonzero": failed+=1
        else: pending+=1
        rows.append({"case_id":cid,"status":qa.get("status"),"pass":qa.get("pass")})
    assert len(seen)==24
    st=load(pkg/"floatinginfo/state0-binding.json")
    assert st["launch_allowed"] is False and st["execution_allowed"] is False
    assert st["future_hashes_null"] is True
    assert st["particle_v0_policy"] == "V0=0 does not prove zero angular velocity"
    result={"schema":"ds02.f6.fresh090.root558-validation.v1","pass":True,"case_count":24,"completed0_pass":completed,"pending":pending,"root558_failed":failed,"rows":rows,"no_science_payload_read_or_hash":True,"native_solver_started_by_validator":False}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))
    return 0
if __name__ == "__main__": raise SystemExit(main())
