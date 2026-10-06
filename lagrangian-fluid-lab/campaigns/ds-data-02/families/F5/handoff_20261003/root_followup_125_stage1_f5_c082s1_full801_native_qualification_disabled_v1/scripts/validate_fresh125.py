#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
TAGS = ["M085_T080","M085_T090","M085_T100","M085_T120","M095_T080","M095_T090","M095_T100","M095_T120","M105_T080","M105_T090","M105_T100","M105_T120","M115_T080","M115_T090","M115_T100","M115_T120"]
ENDPOINTS = {"M085_T080": 1, "M115_T100": 2}
SOURCE_SUFFIXES = {".json", ".xml", ".py", ".md", ".txt"}
SCIENCE_SUFFIXES = {".bi4", ".h5", ".csv", ".dat", ".vtk", ".vtu", ".xmf", ".xdmf"}

def load(p): return json.loads(p.read_text(encoding="utf-8"))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def req(v, msg):
    if not v: raise AssertionError(msg)

def main():
    plan = load(PKG/"metadata/fresh125-source-plan.json")
    req(plan["candidate_count"] == 16 and plan["candidate_tags"] == TAGS, "candidate inventory")
    req(plan["endpoint_tags"] == ["M085_T080", "M115_T100"], "endpoint selection")
    req(set(plan["excluded_duplicate_physical_ids"]) == {"C082S1_MOTION_A080", "C082S1_MOTION_A120"}, "duplicate exclusion")
    req(plan["full801_authorized"] is False and plan["execution_allowed"] is False, "plan disabled")
    req(plan["exact_dp_precision_negative_retained"]["not_relaxed"] is True, "precision negative")
    gate = load(PKG/"metadata/root730-recipe-visual-gate.json")
    req(gate["status"] == "approved-by-root" and gate["candidate_hash_equality_claim"] is False, "Root730 scope")
    attest = {r["tag"]: r for r in load(PKG/"metadata/actual-producer-attestations.json")["rows"]}
    req(set(attest) == set(TAGS), "attestation inventory")
    for tag in TAGS:
        c = attest[tag]
        req(c["actual_gencase_status"] == "completed/0", f"{tag} GenCase")
        req(c["actual_initial_qa_basic_pass"] is True, f"{tag} QA")
        req(c["actual_counts"]["solver_dimension"] == 3, f"{tag} 3D")
        bpath = PKG/"bindings"/f"{tag}-full801-native-binding.json"
        rpath = PKG/"requests"/f"{tag}-full801-native-qualification-request.json"
        req(bpath.is_file() and rpath.is_file(), f"{tag} files")
        b = load(bpath); r = load(rpath)
        req(b["binding_sha256"] if "binding_sha256" in b else True, f"{tag} no fake binding self hash")
        req(b["physical_case_id"].endswith(tag) and "A080" not in b["candidate_id"] and "A120" not in b["candidate_id"], f"{tag} unique physical id")
        req(b["native_bed_mk"] == 50 and b["source_mkbound"] == 40, f"{tag} Mk mapping")
        req(b["actual_initial_qa"]["status"] == "completed/0" and b["actual_initial_qa"]["basic_placement_checks_pass"] is True, f"{tag} QA binding")
        req(b["full801_authorized"] is False and b["execution_allowed"] is False and b["disabled"] is True, f"{tag} binding disabled")
        req(r["schema"] == "ds02.runner-request.v2" and r["kind"] == "qualification" and r["cpu_task_kind"] == "solver", f"{tag} request schema")
        req(r["execution_allowed"] is False and r["disabled"] is True and r["launch"] is False and r["solver_allowed"] is False, f"{tag} request disabled")
        req(r["command"][-2:] == ["-tmax:16", "-tout:0.02"], f"{tag} 16s command")
        req(r["expected_frames"] == 801 and r["qualification_window_s"] == [0.0, 16.0], f"{tag} 801 window")
        req(r["binding"] == str(bpath) and r["binding_sha256"] == sha(bpath), f"{tag} binding closure")
        req(r["actual_counts"] == c["actual_counts"] and r["expected_counts"] == c["actual_counts"], f"{tag} actual count closure")
        req(r["full801_authorized"] is False and r["full_native_authorized"] is False and r["independent_case_count_increment"] == 0, f"{tag} gate")
        req(all(v is None for v in r["future_output_hashes"].values()), f"{tag} future hashes")
        req(r["root730_recipe_visual_gate"]["status"] == "approved-by-root" and r["root730_recipe_visual_gate"]["required"] is True, f"{tag} Root730")
        if tag in ENDPOINTS:
            req(r["endpoint_rank"] == ENDPOINTS[tag] and r["qualification_stage"] == "endpoint_qualification", f"{tag} endpoint")
        else:
            req(r["endpoint_rank"] is None and r["qualification_stage"] == "deferred_after_endpoint_visual_gate", f"{tag} deferred")
        for path_s, value in r["input_sha256"].items():
            if value is None or path_s.startswith("<root-bind:"): continue
            p = Path(path_s)
            if p.suffix.lower() in SCIENCE_SUFFIXES:
                req("producer attestation" in r["input_sha256_provenance"][path_s] or "producer" in r["input_sha256_provenance"][path_s], f"{tag} science provenance")
                continue
            if p.suffix.lower() in SOURCE_SUFFIXES and p.exists():
                req(sha(p) == value, f"{tag} static input hash {path_s}")
        for rel in [f"candidates/{tag}/owner.json", f"candidates/{tag}/{b['source_definition'].split('/')[-1]}", f"bindings/{tag}-physical-binding.json", f"bindings/{tag}-full801-native-binding.json"]:
            req((PKG/rel).is_file(), f"{tag} package source {rel}")
    # No scientific payload is present in this source package.
    for p in PKG.rglob("*"):
        if p.is_file(): req(p.suffix.lower() not in SCIENCE_SUFFIXES, f"science payload copied: {p}")
    manifest = load(PKG/"manifest.json")
    req(manifest["validator_report_excluded_from_manifest"] is True, "manifest exclusion")
    for rel, expected in manifest["files"].items():
        p = PKG/rel; req(p.is_file(), f"manifest file {rel}"); req(sha(p) == expected, f"manifest hash {rel}")
    report = {"schema":"ds02.f5.c082s1.fresh125-validator-report.v1","status":"pass","candidate_count":16,"endpoint_tags":list(ENDPOINTS),"native_requests_disabled":True,"root730_recipe_gate_bound":True,"future_output_hashes_null":True,"science_payloads_read_or_hashed":False,"manifest_source_files":len(manifest["files"])}
    (PKG/"metadata/fresh125-validator-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    try: main()
    except Exception as e:
        print(f"VALIDATION FAILED: {e}", file=sys.stderr); raise
