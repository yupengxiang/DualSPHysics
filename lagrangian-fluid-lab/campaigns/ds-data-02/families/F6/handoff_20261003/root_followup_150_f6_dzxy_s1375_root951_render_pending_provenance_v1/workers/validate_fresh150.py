#!/usr/bin/env python3
"""Bounded metadata-only validator for fresh150 pending render provenance."""
from pathlib import Path
import hashlib, json, sys

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN=(".h5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".pvd")

def digest(path):
    p=Path(path)
    if p.suffix.lower() in FORBIDDEN:
        raise AssertionError(f"forbidden scientific payload: {p}")
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()

def check_ref(item):
    p=Path(item["path"])
    assert p.exists(), p
    assert item.get("exists") is True, p
    assert item.get("sha256") == digest(p), (p, item.get("sha256"), digest(p))

pending=json.loads((ROOT/"metadata/pending-observation.json").read_text())
chain=json.loads((ROOT/"metadata/upstream-chain.json").read_text())
assert pending["schema"] == "ds-data-02.fresh150.pending-render-provenance.v1"
assert pending["status"] == "pending-root951-terminal"
assert pending["visual_review_performed"] is False
assert pending["contact_sheets_viewed"] == 0 and pending["key_frames_viewed"] == 0
assert pending["case_credit"] == 0 and pending["global_credit_updated_by_agent"] is False
assert pending["scientific_payload_read_or_hashed"] is False
assert pending["controller"]["observed_live"] is True
assert pending["controller"]["controller_result_present"] is False
assert pending["controller"]["target_actual_progress_entry_present"] is False
assert pending["target_render"]["submitted_or_terminal"] is False
assert pending["target_render"]["attempt_root_present"] is False
assert pending["target_render"]["receipt_present"] is False
assert pending["target_render"]["render_report_present"] is False
check_ref(pending["controller"]["config"])
check_ref(pending["target_render"]["request"])
check_ref(pending["target_render"]["wrapper_request"])
for item in chain["producer_chain"]:
    check_ref(item["execution_receipt"])
    assert item["producer_request_sha256"]
    j=json.loads(Path(item["execution_receipt"]["path"]).read_text())
    assert j.get("status") == "completed" and j.get("returncode",j.get("return_code")) == 0
    if "metadata_report" in item: check_ref(item["metadata_report"])
check_ref(chain["source_definition"])
check_ref(chain["source_canonical_owner"])
check_ref(chain["classified_converter_owner"])
meta=chain["metadata_only_contract"]
assert meta["native_frames"] == 241 and meta["native_particles"] == 417505 and meta["dimension"] == 3
assert meta["xmf_manifest_frames"] == 241 and meta["xmf_manifest_particles"] == 417505
assert chain["scope_roles"]["source_canonical_physical_condition_sha256"] != chain["scope_roles"]["classified_converter_physical_condition_sha256"]
assert chain["scope_roles"]["source_plan_condition_sha256"]
# Ensure no stored evidence path points to a scientific payload suffix.
blob=json.dumps([pending,chain])
for suffix in FORBIDDEN:
    assert suffix not in blob.lower(), f"forbidden suffix embedded in package metadata: {suffix}"
result={"schema":"ds-data-02.fresh150.validator-result.v1","status":"pass","package":"fresh150","case_id":pending["case_id"],"validated_pending_state":True,"checked_producer_stages":len(chain["producer_chain"]),"scientific_payload_read_or_hashed":False}
(ROOT/"metadata/validator-result.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
print(json.dumps(result,sort_keys=True))
