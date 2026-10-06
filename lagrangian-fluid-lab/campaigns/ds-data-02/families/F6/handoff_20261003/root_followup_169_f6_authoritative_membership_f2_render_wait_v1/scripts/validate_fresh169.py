#!/usr/bin/env python3
"""Validate F6 fresh169 membership and frozen F2 wait metadata only."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

FORBIDDEN=(".h5", ".bi4", ".csv", ".dat", ".vtk")
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()
def check_ref(x):
    p=Path(x["path"]); assert p.is_file(), p
    assert x["sha256"] == sha(p), (p, "sha drift")
    assert not any(str(p).lower().endswith(s) for s in FORBIDDEN), p
    assert p.stat().st_size == x["bytes"], (p, "size drift")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--package", type=Path, default=Path(__file__).parents[1]); args=ap.parse_args()
    d=json.load((args.package/"metadata/authoritative-membership.json").open())
    assert d["schema"] == "ds02.f6.fresh169.authoritative-membership-and-f2-render-wait.v1"
    assert d["family_id"] == "F6" and d["fresh_id"] == "fresh169"
    for x in d["authoritative_sources"]: check_ref(x)
    f8=d["first8_authoritative"]; f24=d["first24_actual_visual_membership"]; s24=d["second24_actual_visual_membership"]; f48=d["final48_membership"]
    ids8=[x["case_id"] for x in f8["rows"]]; ids24=[x["case_id"] for x in f24["rows"]]; ids2=[x["case_id"] for x in s24["rows"]]; ids48=[x["case_id"] for x in f48["rows"]]
    assert len(ids8)==8 and len(set(ids8))==8
    assert len(ids24)==24 and len(set(ids24))==24
    assert len(ids2)==24 and len(set(ids2))==24 and not set(ids24)&set(ids2)
    assert set(ids8) <= set(ids24)
    assert len(ids48)==48 and len(set(ids48))==48
    assert f48["actual_visual_accepted_count"]==47 and f48["pending_visual_decision_count"]==1
    assert s24["pending_case_ids"] == ["F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025"]
    for row in f24["rows"]:
        dec=row.get("visual_decision"); assert dec and dec.get("status"," ").startswith("visual-approved")
        check_ref(dec)
        q=json.load(Path(dec["path"]).open()); assert q.get("family_id")=="F6" and q.get("case_id")==row["case_id"]
    for row in s24["rows"]:
        dec=row.get("visual_decision")
        if dec is None:
            assert row["case_id"]=="F6_STAGE1_ANGULAR_RELEASE_DZXY_S1375_YAWP18_DP025"
            continue
        assert dec.get("status"," ").startswith("visual-approved")
        check_ref(dec)
        q=json.load(Path(dec["path"]).open()); assert q.get("family_id")=="F6" and q.get("case_id")==row["case_id"]
    pend=[x for x in s24["rows"] if x.get("visual_decision") is None]; assert len(pend)==1
    fw=d["f2_render_frontier"]; assert fw["snapshot_kind"]=="frozen_pre_terminal_wait_observation" and not fw["eligible_for_personal_visual_review_at_snapshot"]
    for key in ("registered_request","wrapper","controller_config","controller_launch","typed_xmf_metadata_review"):
        check_ref(fw[key])
    assert fw["controller_result_at_snapshot"]["exists_at_snapshot"] is False
    assert fw["execution_receipt_at_snapshot"]["exists_at_snapshot"] is False
    assert d["source_boundaries"]["science_payload_read"] is False and d["source_boundaries"]["science_payload_hashed"] is False
    print("fresh169 validation PASS: first8=8 first24=24 second24=23accepted+1pending final48=47accepted+1pending; F2=historical wait snapshot")
if __name__=="__main__": main()
