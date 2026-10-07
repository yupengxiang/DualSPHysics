#!/usr/bin/env python3
"""Read-only validator for fresh231's checkpoint-333 completion audit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".png", ".xmf"}


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def check(ok, msg):
    if not ok:
        raise AssertionError(msg)


def main():
    m = load("manifest.json")
    check(m["schema"] == "ds02.f5.fresh231.source-only-manifest.v1", "manifest schema")
    check(m["source_only"] is True and m["scientific_payload_IO"] is False, "source-only policy")
    check(m["goal_complete_claim"] is False, "goal completion claim")
    check(m["case_credit"] == 0 and m["Q_N"] is False and m["Q_E"] is False, "credit/Q flags")
    for item in m["files"]:
        p = ROOT / item["path"]
        check(p.is_file(), f"missing file: {item['path']}")
        check(p.suffix.lower() not in FORBIDDEN, f"payload suffix: {item['path']}")
        check(hashlib.sha256(p.read_bytes()).hexdigest() == item["sha256"], f"SHA mismatch: {item['path']}")
    for p in ROOT.rglob("*"):
        if p.is_file():
            check(p.suffix.lower() not in FORBIDDEN, f"payload in package: {p}")

    s = load("metadata/current-state.json")["checkpoint"]
    check(s["checkpoint_number"] == 333, "checkpoint")
    check(s["stage1_visual_accepted_complete_independent_cases"] == 336, "accepted count")
    check(all(v == 48 for v in s["accepted_per_family"].values()), "family counts")
    check(s["active_reservations"] == 0, "active reservations")
    check("Do not declare full goal achieved" in s["authorized_work_state"], "checkpoint hold")
    check(s["goal_completion_audit_status"].startswith("unproven"), "goal audit hold")

    req = load("metadata/requirement-audit.json")
    check(len(req["requirements"]) == 8, "requirement rows")
    check(req["requirements"][-1]["result"] == "hold", "global hold")

    fm = load("metadata/family-matrix.json")
    direct = fm["root1451_direct_proof"]
    check(direct["all336_selected_xmf_xml_fulltimes_geometry_velocity_n3_verified"] is True, "direct XMF/N3 proof")
    check(direct["all336_animation_report_flags_verified"] is True, "animation proof")
    check(direct["explicit_membership_verified"] is True, "membership proof")
    check("pending" in direct["physical_distinction_status"], "physical distinction hold")
    check(all(v["accepted"] == 48 and v["pending"] == 0 for v in fm["families"].values()), "family matrix")

    refs = load("metadata/evidence-refs.json")
    check(refs["root1451_direct_proof"]["sha256"] == "169c00291b1aa0e02e91d1cce7819a0fa4a19536f8a39e61b2be2cc039061b22", "root1451 ref")
    print("fresh231 validator: PASS (336/336 primary metadata; goal remains held for audit194/requirement230)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
