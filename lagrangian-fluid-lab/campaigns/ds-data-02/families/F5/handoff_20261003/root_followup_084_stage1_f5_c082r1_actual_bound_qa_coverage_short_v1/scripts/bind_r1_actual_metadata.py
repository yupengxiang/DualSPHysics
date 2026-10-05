#!/usr/bin/env python3
"""Bind an already completed R1 GenCase using JSON/XML metadata only.

The helper deliberately never opens the BI4.  Its producer-declared BI4 SHA is
carried as opaque provenance; native QA is the later Root-owned PartVTK stage.
"""
from __future__ import annotations
import argparse, hashlib, json, xml.etree.ElementTree as ET
from pathlib import Path

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block=stream.read(1024*1024)
            if not block: break
            h.update(block)
    return h.hexdigest()
def require(ok, msg):
    if not ok: raise ValueError(msg)
def load(path, expected, label):
    path=Path(path); require(path.is_file(), f"{label} missing: {path}")
    actual=sha256_file(path); require(actual==expected, f"{label} SHA mismatch: {actual} != {expected}")
    return json.loads(path.read_text(encoding="utf-8"))
def xml_counts(path):
    root=ET.parse(path).getroot(); require(root.tag=="case", "generated XML root is not case")
    data2d=root.find("./execution/constants/data2d")
    require(data2d is not None and data2d.get("value", "true").lower()=="false", "generated XML is not 3-D")
    p=root.find("./execution/particles"); require(p is not None, "particles metadata missing")
    counts={}
    for n in p:
        if n.tag in {"fixed","moving","floating","fluid"}:
            counts[n.tag]=counts.get(n.tag,0)+int(n.get("count","-1"))
    total=int(p.get("np","-1")); require(total>0 and sum(counts.values())==total, "XML particle blocks do not sum to np")
    return total, counts

def main():
    ap=argparse.ArgumentParser();
    ap.add_argument("--actual-binding",type=Path,required=True); ap.add_argument("--actual-request",type=Path,required=True)
    ap.add_argument("--receipt",type=Path,required=True); ap.add_argument("--prepared-report",type=Path,required=True)
    ap.add_argument("--generated-xml",type=Path,required=True); ap.add_argument("--source-definition",type=Path,required=True)
    ap.add_argument("--canonical-recipe",type=Path,required=True); ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args(); raw=json.loads(a.actual_binding.read_text(encoding="utf-8")); request=json.loads(a.actual_request.read_text(encoding="utf-8"))
    actual_binding_sha=sha256_file(a.actual_binding); actual_request_sha=sha256_file(a.actual_request)
    require(raw.get("case_id")==request.get("case_id"), "actual binding/request case mismatch")
    require(raw.get("condition_id")==request.get("condition_id"), "actual binding/request condition mismatch")
    receipt=load(a.receipt, raw["input_receipt_sha256"] if raw.get("input_receipt_sha256") else sha256_file(a.receipt), "GenCase receipt")
    report=load(a.prepared_report, raw["input_report_sha256"] if raw.get("input_report_sha256") else sha256_file(a.prepared_report), "prepared report")
    # Re-read hashes only for the small JSON/XML/source files.  BI4 remains opaque.
    receipt_sha=sha256_file(a.receipt); report_sha=sha256_file(a.prepared_report); xml_sha=sha256_file(a.generated_xml)
    def_sha=sha256_file(a.source_definition); canonical_sha=sha256_file(a.canonical_recipe)
    require(receipt.get("status")=="completed" and receipt.get("returncode")==0, "GenCase receipt is not completed/zero")
    require(receipt.get("request",{}).get("case_id")==request.get("case_id"), "nested receipt case mismatch")
    require(receipt.get("request",{}).get("attempt_id")==request.get("attempt_id"), "nested receipt attempt mismatch")
    require(receipt.get("solver_dimension_from_gencase")==3, "GenCase is not 3-D")
    total=int(receipt["total_particles"]); fluid=int(receipt["fluid_particles"])
    xml_total, xml_counts_by_kind=xml_counts(a.generated_xml)
    report_counts=report.get("generated_xml_particle_counts",{})
    require(xml_total==total and report.get("actual_total_particles")==total, "actual totals disagree")
    require({"fixed":xml_counts_by_kind.get("fixed"),"moving":xml_counts_by_kind.get("moving"),"floating":xml_counts_by_kind.get("floating",0),"fluid":xml_counts_by_kind.get("fluid")}==report_counts, "report/XML counts disagree")
    require(xml_counts_by_kind.get("fluid")==fluid, "XML/receipt fluid count disagree")
    output_root=Path(receipt["output_root"]).resolve(); require(output_root==a.receipt.parent.resolve(), "receipt output_root is not the actual attempt root")
    raw_bi4=raw.get("generated_bi4",{}); require(raw_bi4.get("sha256")==report.get("bi4_sha256"), "producer BI4 SHA mismatch")
    result={
      "schema":"ds02.f5.c082r1.actual-gencase-binding.v1", "status":"actual_completed_metadata_bound",
      "case_id":request["case_id"], "attempt_id":request["attempt_id"], "condition_id":request["condition_id"],
      "candidate_id":raw.get("candidate_id"), "physical_case_id":raw.get("physical_case_id"),
      "physical_condition_sha256":raw.get("physical_condition_sha256"),
      "source_plan_physical_condition_sha256":raw.get("source_plan_physical_condition_sha256"),
      "source_definition":str(a.source_definition), "source_definition_sha256":def_sha,
      "canonical_recipe":str(a.canonical_recipe), "canonical_recipe_sha256":canonical_sha,
      "actual_request":str(a.actual_request), "actual_request_sha256":actual_request_sha,
      "actual_gencase_binding":str(a.actual_binding), "actual_gencase_binding_sha256":actual_binding_sha,
      "gencase_receipt":str(a.receipt), "gencase_receipt_sha256":receipt_sha,
      "prepared_input_report":str(a.prepared_report), "prepared_input_report_sha256":report_sha,
      "generated_xml":str(a.generated_xml), "generated_xml_sha256":xml_sha,
      "generated_bi4":str(raw_bi4.get("path")), "generated_bi4_sha256":raw_bi4.get("sha256"),
      "gencase_output_root":str(output_root),
      "actual_counts":{"total_particles":total,"fixed_particles":xml_counts_by_kind.get("fixed",0),"moving_particles":xml_counts_by_kind.get("moving",0),"floating_particles":xml_counts_by_kind.get("floating",0),"fluid_particles":fluid,"solver_dimension":3,"xml_particle_counts":report_counts},
      "source_marker_mapping":{"source_mkbound":40,"native_bed_mk":50}, "dp_m":0.02,
      "profile":{"x_bounds_m":[-0.2,4.8],"bed_y_bounds_m":[-0.22,0.22],"fluid_y_bounds_m":[-0.14,0.14],"nodes_xz_m":[[-0.2,0.0],[2.0,0.0],[3.0,0.28],[3.6,0.448],[3.9,0.448],[4.4,0.05],[4.8,0.05]]},
      "motion_asset":{"path":raw["assets"][0]["source"],"relative_name":raw["assets"][0]["relative_name"],"sha256":raw["assets"][0]["sha256"]},
      "continuum_fluid_mass_kg":325.7142857142857,
      "expected_fluid":None,
      "producer_contract":{"actual_counts_only":True,"no_old_fluid_count_substitution":True,"bi4_sha256_provenance":"producer-declared; not opened by metadata binder"},
      "execution_policy":{"arrays_allowed":False,"solver_allowed":False,"conversion_allowed":False,"independent_case_count_increment":0,"full16_authorized":False,"full801_authorized":False},
      "arrays_opened_by_source_agent":False,
    }
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({"status":result["status"],"actual_counts":result["actual_counts"],"output":str(a.output)},sort_keys=True))
if __name__=="__main__": main()
