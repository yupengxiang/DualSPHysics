#!/usr/bin/env python3
"""Static Root648 NVMe argv check; never executes converter code."""
import argparse,ast,json
from pathlib import Path
DIRECT="ds_data02_direct_convert.py"
def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def parser_source(p):
    text=p.read_text(encoding="utf-8"); ast.parse(text)
    assert "ArgumentParser" in text and "parse_args" in text
    return {"path":str(p),"remainder":"argparse.REMAINDER" in text,"data_root":"--data-root" in text,"direct_parse":"_build_parser().parse_args(argv)" in text}
def check(cmd):
    assert cmd[1].endswith("ds_data02_nvme_convert_v1.py")
    i=cmd.index("--"); tail=cmd[i+1:]
    assert tail and tail[0]=="--data-root"
    assert DIRECT not in tail and not any(Path(x).name==DIRECT for x in tail)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--package",type=Path,required=True); a=ap.parse_args(); p=a.package.resolve()
    m=load(p/"metadata/nvme-argv-contract.json"); parser_source(Path(m["wrapper"]["path"])); parser_source(Path(m["direct_converter_parser"]["path"]))
    qs=sorted((p/"requests").glob("*-typed-nvme-*.json")); assert len(qs)==24
    for q in qs:
        d=load(q); check(d["command"]); assert d["disabled"] and not d["execution_allowed"]
    bad=list(load(qs[0])["command"]); bad[bad.index("--")+1:bad.index("--")+1]=[DIRECT]
    try: check(bad)
    except AssertionError: pass
    else: raise AssertionError("historical bad positional token accepted")
    print("fresh105 NVMe argv contract: PASS (24 corrected commands; bad-token regression rejected)")
if __name__=="__main__": main()
