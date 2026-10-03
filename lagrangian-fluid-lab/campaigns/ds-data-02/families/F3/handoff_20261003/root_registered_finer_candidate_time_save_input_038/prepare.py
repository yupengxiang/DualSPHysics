import argparse,hashlib,json,re,shutil,xml.etree.ElementTree as ET
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--binding",required=True);p.add_argument("--output-dir",required=True);a=p.parse_args();b=json.loads(Path(a.binding).read_text());out=Path(a.output_dir);out.mkdir(exist_ok=False)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
for key in ["source_gen_receipt","source_native_receipt","source_qa_receipt"]:
 r=json.loads(Path(b[key]).read_text());assert r["status"]=="completed" and r["returncode"]==0
assert sha(b["source_bi4"])==b["source_bi4_sha256"] and sha(b["source_control"])==b["source_control_sha256"]
text=Path(b["source_xml"]).read_text();original=ET.fromstring(text);c=original.find("./execution/constants");assert float(c.find("dp").get("value"))==.006 and c.find("data2d").get("value")=="false" and float(c.find("cflnumber").get("value"))==.05
particles=original.find("./execution/particles");assert int(particles.get("np"))==179208 and int(particles.find("fluid").get("count"))==67500
params={e.get("key"):e.get("value") for e in original.findall("./execution/parameters/parameter")}
for key,value in {"CoefDtMin":.005,"TimeMax":8.35,"TimeOut":.01,"DtFixed":0,"StepAlgorithm":2}.items():assert float(params[key])==value
head,tail=text.split("<execution>",1);head+="<execution>";rows=[]
for target in b["targets"]:
 d=out/target["role"];d.mkdir();prefix=d/target["case_id"];new=tail
 for pattern,value in [(r'(<cflnumber\b[^>]*value=["\'])[^"\']+(["\'])',target["cfl"]),(r'(<parameter\b[^>]*key=["\']CoefDtMin["\'][^>]*value=["\'])[^"\']+(["\'])',target["coef_dt_min"])]:
  new,n=re.subn(pattern,lambda m:m[1]+str(value)+m[2],new);assert n==1
 restored=new
 for pattern,value in [(r'(<cflnumber\b[^>]*value=["\'])[^"\']+(["\'])',c.find("cflnumber").get("value")),(r'(<parameter\b[^>]*key=["\']CoefDtMin["\'][^>]*value=["\'])[^"\']+(["\'])',params["CoefDtMin"])]:
  restored,n=re.subn(pattern,lambda m:m[1]+value+m[2],restored);assert n==1
 assert restored==tail
 # Dense control uses original XML bytes; actual output frequency is an explicit solver CLI control.
 if target["role"]=="dense":new=tail
 x=prefix.with_suffix(".xml");x.write_text(head+new);bi=prefix.with_suffix(".bi4");shutil.copyfile(b["source_bi4"],bi);ctrl=d/Path(b["source_control"]).name;shutil.copyfile(b["source_control"],ctrl)
 assert sha(bi)==b["source_bi4_sha256"] and sha(ctrl)==b["source_control_sha256"]
 undone=ET.fromstring(x.read_text());undone.find("./execution/constants/cflnumber").set("value",c.find("cflnumber").get("value"));undone.find("./execution/parameters/parameter[@key='CoefDtMin']").set("value",params["CoefDtMin"])
 assert ET.tostring(undone)==ET.tostring(original)
 rows.append({**target,"prefix":str(prefix),"xml_sha256":sha(x),"initial_bi4_sha256":sha(bi),"control_sha256":sha(ctrl),"discrete_initial_byte_identical":True,"actual_total_particles":179208,"actual_fluid_particles":67500,"historical_casedef_unchanged":True,"XML_TimeOut_s":.01})
assert sha(b["source_bi4"])==b["source_bi4_sha256"] and sha(b["source_control"])==b["source_control_sha256"]
(out/"clone-report.json").write_text(json.dumps({"schema":"ds02.f3.dp006-time-save-clones.v1","cases":rows,"actual_source_gen_receipt":b["source_gen_receipt"],"q_n":"not_granted","production_approval":"none"},indent=2)+"\n")
