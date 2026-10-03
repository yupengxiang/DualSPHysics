import argparse,hashlib,json,re,shutil,xml.etree.ElementTree as ET
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--binding",required=True);p.add_argument("--output-dir",required=True);a=p.parse_args();b=json.loads(Path(a.binding).read_text());out=Path(a.output_dir);out.mkdir(exist_ok=True)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
r=json.loads(Path(b["source_solver_receipt"]).read_text());assert r["status"]=="completed" and r["returncode"]==0
text=Path(b["source_xml"]).read_text();original=ET.fromstring(text);assert float(original.find(".//execution/constants/cflnumber").get("value"))==b["baseline_cfl"]
params={e.get("key"):e.get("value") for e in original.findall(".//execution/parameters/parameter")};assert float(params["CoefDtMin"])==b["baseline_coef_dt_min"]
new,n=re.subn(r'(<cflnumber\b[^>]*value=["\'])[^"\']+(["\'])',lambda m:m[1]+str(b["candidate_cfl"])+m[2],text);assert n==1
new,n=re.subn(r'(<parameter\b[^>]*key=["\']CoefDtMin["\'][^>]*value=["\'])[^"\']+(["\'])',lambda m:m[1]+str(b["candidate_coef_dt_min"])+m[2],new);assert n==1
# Undoing only the two registered literal control changes recovers original bytes.
restored,n=re.subn(r'(<cflnumber\b[^>]*value=["\'])[^"\']+(["\'])',lambda m:m[1]+original.find(".//execution/constants/cflnumber").get("value")+m[2],new);assert n==1
restored,n=re.subn(r'(<parameter\b[^>]*key=["\']CoefDtMin["\'][^>]*value=["\'])[^"\']+(["\'])',lambda m:m[1]+params["CoefDtMin"]+m[2],restored);assert n==1 and restored==text
prefix=out/"F1_ECC_THICK_DBC_MEDIUM_GENUINE_HALF_CFL001";xml=prefix.with_suffix(".xml");bi=prefix.with_suffix(".bi4");assert not xml.exists() and not bi.exists();xml.write_text(new);shutil.copyfile(b["source_bi4"],bi);assert sha(bi)==b["source_bi4_sha256"]
report={"schema":"ds02.f1.thick-dbc-halfstep-input-preparation.v1","prepared_prefix":str(prefix),"prepared_xml":str(xml),"prepared_bi4":str(bi),"prepared_xml_sha256":sha(xml),"prepared_bi4_sha256":sha(bi),"only_xml_changes":{"CFLnumber":[.2,.1],"CoefDtMin":[.05,.025]},"initial_bi4_byte_identical":True,"physical_condition_sha256":b["physical_condition_sha256"],"q_n":"not_granted","production_approval":"none"};(out/"prepared-input-report.json").write_text(json.dumps(report,indent=2)+"\n")
