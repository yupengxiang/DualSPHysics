#!/usr/bin/env python3
"""Validate fresh105 source metadata without scientific payload access."""
import argparse,json
from pathlib import Path
RAW={".bi4",".h5",".hdf5",".vtk",".vtu",".vtp",".csv",".dat"}
def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--package",type=Path,required=True); a=ap.parse_args(); p=a.package.resolve()
    m=load(p/"manifest.json"); idx=load(p/"requests/index.json"); assert m["case_count"]==24 and m["request_count"]==72 and idx["all_disabled"]
    assert len(idx["requests"])==72
    kinds={k:[] for k in ("typed","xmf","render")}; cases=set()
    for row in idx["requests"]:
        q=load(row["path"]); kinds[row["kind"]].append(q); cases.add(q["case_id"])
        assert row["disabled"] and q["disabled"] and not q["execution_allowed"] and not q.get("launch") and not q.get("launch_allowed")
        assert q["source_only"] and not q["jobs_started_by_source"] and q["shared_registry_write_by_source"] is False
        for x in q.get("future_hashes",{}).values(): assert x is None
        for x in q.get("future_render_hashes",{}).values(): assert x is None
        for path in q.get("input_files",[]): assert Path(path).suffix.lower() not in RAW
        assert all(x is None for x in q.get("deferred_input_sha256",{}).values())
        for k,x in q.get("expected_outputs",{}).items():
            if k.endswith("sha256") or k in {"all_sha256","output_sha256"}: assert x is None
    assert cases and len(cases)==24 and all(len(kinds[k])==24 for k in kinds)
    typed={q["case_id"]:q for q in kinds["typed"]}; xmf={q["case_id"]:q for q in kinds["xmf"]}; render={q["case_id"]:q for q in kinds["render"]}
    assert set(typed)==set(xmf)==set(render)==cases
    for case,q in typed.items():
        tail=q["command"][q["command"].index("--")+1:]; assert tail[0]=="--data-root" and "ds_data02_direct_convert.py" not in tail
        assert q["root647_failure_evidence"]["returncode"]==2 and q["root648_repair_evidence"]["corrected_argv"] is True
        assert q["actual_typed_status"]["completed0_receipt"] is None
        assert xmf[case]["depends_on_attempts"]==[q["attempt_id"]]
        assert render[case]["depends_on_attempts"]==[xmf[case]["attempt_id"]]
        assert render[case]["cpu_threads"]==24 and render[case]["root_cpu_reservation_policy"]["conservative_reserved_cpu_threads"]==24
        assert render[case]["root_cpu_reservation_policy"]["explicit_environment_threads"]["VTK_SMP_MAX_THREADS"]==2
    e=load(p/"evidence/upstream-root616-root619-root623-root626.json"); assert e["case_count"]==24 and e["root619_native_completed0"]==24 and e["root623_frame0_completed_pass"]==24
    pre=load(p/"evidence/converter-physical-scope-preflight.json"); assert pre["all_pass"] and len(pre["cases"])==24 and all(x["source_owner_hash_reused"] is False for x in pre["cases"])
    print("fresh105 source contract: PASS (24 disabled typed + 24 disabled XMF + 24 disabled Root023; Root647/648 evidence and Root638 env contract)")
if __name__=="__main__": main()
