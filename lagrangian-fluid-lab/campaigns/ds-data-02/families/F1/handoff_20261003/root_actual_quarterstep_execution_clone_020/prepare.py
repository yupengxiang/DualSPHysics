import argparse,importlib.util,json,xml.etree.ElementTree as ET
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--binding",required=True);p.add_argument("--output-dir",required=True);a=p.parse_args();b=json.loads(Path(a.binding).read_text());out=Path(a.output_dir);assert not out.exists()
for key in ["source_prepare_receipt","source_halfstep_native_receipt"]:
 r=json.loads(Path(b[key]).read_text());assert r["status"]=="completed" and r["returncode"]==0
src=Path(b["source_halfstep_input_preparation"]["prepared_xml"]);original=ET.fromstring(src.read_text());assert float(original.find("./execution/constants/cflnumber").get("value"))==.1 and float(original.find("./execution/constants/dp").get("value"))==.005
s=importlib.util.spec_from_file_location("selected_quarter",Path(__file__).with_name("selected_transformer.py"));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
r=m.prepare_quarterstep_inputs(a.binding,out);new=ET.fromstring(Path(r["prepared_xml"]).read_text());new.find("./execution/constants/cflnumber").set("value",original.find("./execution/constants/cflnumber").get("value"));new.find("./execution/parameters/parameter[@key='CoefDtMin']").set("value",original.find("./execution/parameters/parameter[@key='CoefDtMin']").get("value"));assert ET.tostring(new)==ET.tostring(original)
assert r["initial_bi4_byte_identical"] and r["whole_xml_reversebytes_verified"] and r["only_xml_changes"]=={"CFLnumber":[.1,.05],"CoefDtMin":[.025,.0125]}
print(json.dumps({"actual_execution_clone_prepared":True,"same_initial_BI4":True,"q_n":"not_granted"}))
