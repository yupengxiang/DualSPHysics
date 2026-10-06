#!/usr/bin/env python3
import hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXPECTED=2
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()
idx=json.loads((ROOT/"metadata/visual-frontier-index.json").read_text())
assert idx["batch_size"]==EXPECTED and idx["independent_case_increment"]==0
assert idx["status"]=="visual-approved-by-delegated-agent" and len(idx["decision_paths"])==EXPECTED
resolution=json.loads((ROOT/"metadata/identifier-resolution.json").read_text())
assert resolution["requested_rx060_rotation_rows_present"] is False
assert all("RX060" not in x for x in resolution["actual_root792_rows_used"])
for rel in idx["decision_paths"]:
    d=json.loads((ROOT/rel).read_text())
    assert d["family_id"]=="F2" and d["status"]=="visual-approved-by-delegated-agent"
    assert d["review_method"]["contact_sheets_reviewed"]==17
    assert d["review_method"]["fullsize_keyframes_reviewed"]==[0,65,115,400]
    e=d["render_metadata_evidence"]
    assert e["frames"]==401 and e["source_frames"]==401 and e["all_frames_rendered"] is True
    assert e["actual_times_preserved_exactly"] is True and e["nonfinite_active_states"]==0
    assert e["all_finite_positions"] is True and e["all_finite_fields"] is True
    assert e["framewise_identity_exclusions_observed"] is (e["framewise_missing_particles_max"]>0)
    assert e["framewise_exclusions_preserved_without_fill"] is True
    assert d["uid_and_finiteness_evidence"]["framewise_uid_loss_observed"] is (e["framewise_missing_particles_max"]>0)
    scopes=d["physical_scope_provenance"]
    assert scopes["actual_converter_scope"]["separate_from_canonical_source_scope"] is True
    assert scopes["legacy_converter_scope"]["payload_hash_recomputed"] is False
    assert d["claim_limits"]["qualification_or_precision_grant"] is False
    assert d["claim_limits"]["production_approval_grant"] is False
    assert len(d["bindings"]["render"]["contact_sheets"])==17
    assert len(d["bindings"]["render"]["keyframes"])==4
    for item in d["bindings"]["render"]["contact_sheets"]+d["bindings"]["render"]["keyframes"]:
        p=Path(item["path"]); assert p.is_file(), p
        assert sha(p)==item["sha256"], p
        assert not any(x in item["path"].lower() for x in (".h5",".bi4",".csv",".dat",".vtk"))
    for n in ("actual_gencase_receipt_status","actual_initial_qa_receipt_status","actual_native_receipt_status","actual_typed_receipt_status","actual_xmf_receipt_status","actual_render_receipt_status"):
        assert d["provenance_status"][n]=="completed"
print("fresh097 F2 visual metadata + rendered-PNG hash validation: PASS")
