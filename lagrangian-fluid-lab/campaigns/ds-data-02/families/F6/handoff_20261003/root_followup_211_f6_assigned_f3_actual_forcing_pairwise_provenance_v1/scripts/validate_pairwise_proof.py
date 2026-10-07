#!/usr/bin/env python3
"""Read-only certificate validator; it never opens referenced producer files."""
import copy
import json
import math
import sys
from pathlib import Path

FIELDS = ("drive_amplitude_G", "amplitude_x", "amplitude_y", "omega_y", "phase_y", "tau_ramp")
SCHEMA = "ds02.f6.fresh211.f3-actual-forcing-pairwise-provenance.v1"

def fail(msg):
    raise AssertionError(msg)

def check(d):
    if d.get("schema") != SCHEMA: fail("schema")
    b = d.get("source_boundaries", {})
    if b.get("json_xml_only") is not True or b.get("scientific_payloads_read_or_hashed") is not False: fail("boundary")
    if b.get("jobs_started") or b.get("shared_state_modified") or b.get("case_credit") != 0: fail("side effect")
    if not {"fresh208", "root1456", "fresh209", "fresh210"} <= set(d.get("inputs", {})): fail("input closure")
    for x in d["inputs"].values():
        if x.get("exists") is not True or not isinstance(x.get("sha256"), str) or len(x["sha256"]) != 64: fail("input ref")
    rows = d.get("rows", []); ids = [r.get("physical_case_id") for r in rows]
    if len(rows) != 48 or len(set(ids)) != 48: fail("rows/id")
    running = []
    for r in rows:
        if not r.get("case_id") or r.get("producer_report", {}).get("path", "").endswith(".json") is False: fail("report ref")
        if Path(r["metadata_sha_join"]["native_xml"].get("path", "x")).suffix.lower() not in (".xml", ".xmf"): fail("xml ref")
        n = r.get("forcing_numeric_fields", {})
        if set(n) != set(FIELDS) or any(isinstance(n[k], bool) or not isinstance(n[k], (int, float)) or not math.isfinite(n[k]) for k in FIELDS): fail("producer numeric")
        if r.get("producer_forcing", {}).get("report_binding_amplitude_y_matches_transform") is not True: fail("report/transform")
        for j in (r["metadata_sha_join"]["producer_report"], r["metadata_sha_join"]["native_xml"]):
            if not (j.get("launch_matches_metadata") is True and isinstance(j.get("metadata_sha256"), str) and len(j["metadata_sha256"]) == 64): fail("launch metadata join")
        out = r.get("producer_output", {})
        if out.get("payload_opened_or_hashed") is not False or "sha256" in out or not out.get("producer_attested_sha256"): fail("payload boundary")
        if out.get("launch_matches_producer") is not True: fail("producer launch join")
        if r.get("native_status") == "running":
            running.append(r["physical_case_id"])
            if r.get("native_returncode") is not None or r["running_role"].get("after_state") != "unknown" or r["running_role"].get("original_status_rewritten") is not False or not r["running_role"].get("downstream_recovery_is_separate"): fail("running role")
            if any(r["metadata_sha_join"][k].get("after_matches_metadata") for k in ("producer_report", "native_xml")) or out.get("after_matches_producer") is not None: fail("running after fabricated")
        elif r.get("native_status") == "completed":
            if r.get("native_returncode") != 0 or r["running_role"].get("after_state") != "available": fail("completed receipt")
            if any(r["metadata_sha_join"][k].get("after_matches_metadata") is not True for k in ("producer_report", "native_xml")) or out.get("after_matches_producer") is not True: fail("after metadata join")
        else: fail("status")
    if len(running) != 4 or running != d["summary"].get("running_rows_preserved"): fail("running set")
    pairs = d.get("pairwise_comparisons", [])
    if len(pairs) != 1128 or any(p["left"] not in ids or p["right"] not in ids or not set(p["shared_known_fields"]) == set(FIELDS) or not p["different_fields"] or p["all_shared_fields_equal"] for p in pairs): fail("pairwise")
    s = d.get("summary", {})
    if s.get("rows") != 48 or s.get("pair_count") != 1128 or s.get("pairs_with_known_difference") != 1128 or s.get("pairs_equal_on_all_shared_fields") != 0 or s.get("forcing_numeric_collision_groups") != {}: fail("summary")
    if d.get("numeric_comparison_policy", {}).get("producer_report_is_authoritative") is not True or d["numeric_comparison_policy"].get("identifier_pitch_resolution_time_view_excluded") is not True: fail("comparison policy")

def main():
    positional = [a for a in sys.argv[1:] if a != "--self-test"]
    p = Path(positional[0]) if positional else Path(__file__).resolve().parents[1] / "metadata/f3-actual-forcing-pairwise-provenance.json"
    d = json.loads(p.read_text()); check(d)
    if "--self-test" in sys.argv:
        bad = copy.deepcopy(d); i = next(i for i, r in enumerate(bad["rows"]) if r["native_status"] == "running"); bad["rows"][i]["native_status"] = "completed"; bad["rows"][i]["native_returncode"] = 0
        try: check(bad)
        except AssertionError: pass
        else: fail("negative running-after test")
        bad = copy.deepcopy(d); bad["rows"][1]["forcing_numeric_fields"].pop("amplitude_y")
        try: check(bad)
        except AssertionError: pass
        else: fail("negative numeric field test")
    print(json.dumps({"schema": SCHEMA, "status": "PASS", "rows": 48, "pairs": 1128, "running": 4}, sort_keys=True))

if __name__ == "__main__": main()
