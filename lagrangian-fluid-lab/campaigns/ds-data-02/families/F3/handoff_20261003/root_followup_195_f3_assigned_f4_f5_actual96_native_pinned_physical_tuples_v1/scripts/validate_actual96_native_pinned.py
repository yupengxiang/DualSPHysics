#!/usr/bin/env python3
"""Read-only recheck for the F4/F5 native-pinned numeric tuple report."""
import hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPORT = HERE / "metadata" / "f4-f5-actual96-native-pinned-tuples.json"
F4 = {"gap_m", "x_offset_m", "y_offset_m", "speed_m_per_s"}
F5 = {"amplitude_scale", "time_scale"}
SPECIAL = {"F5_COMPACT_RUNUP_RECOVERY_C082S1_A080", "F5_COMPACT_RUNUP_RECOVERY_C082S1_A120"}
FORBIDDEN = (".bi4", ".h5", ".csv", ".dat", ".vtk", ".png")

def fail(msg):
    raise SystemExit("FAIL: " + msg)

def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def walk(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            q = f"{path}.{k}" if path else k
            yield q, v
            yield from walk(v, q)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from walk(v, f"{path}[{i}]")

def main():
    d = json.loads(REPORT.read_text())
    if d.get("schema") != "ds02.fresh195.f4-f5.actual96.native-pinned-physical-tuples.v1": fail("schema")
    if d.get("source_boundaries", {}).get("scientific_payloads_read_or_hashed") is not False: fail("payload boundary")
    rows = d.get("rows", [])
    if len(rows) != 96: fail(f"row count {len(rows)}")
    counts = {f: sum(r.get("family_id") == f for r in rows) for f in ("F4", "F5")}
    if counts != {"F4": 48, "F5": 48}: fail(f"family counts {counts}")
    for r in rows:
        fam, pid = r.get("family_id"), r.get("physical_case_id")
        keys = set(r.get("normalized_tuple", {}))
        allowed = F4 if fam == "F4" else F5
        if fam not in {"F4", "F5"} or not keys <= allowed: fail(f"tuple keys {pid}")
        missing = set(r.get("missing_known_fields", []))
        if fam == "F4" and keys != F4: fail(f"F4 incomplete tuple {pid}")
        if fam == "F5" and (keys != F5 and not (pid in SPECIAL and keys == {"amplitude_scale"} and missing == {"time_scale"})): fail(f"F5 tuple {pid}")
        rec = r["native_receipt"]; rp = Path(rec["path"]); sp = Path(r["selected_native_input"]["path"])
        if rp.suffix != ".json" or sp.suffix != ".json" or not rp.is_file() or not sp.is_file(): fail(f"metadata path {pid}")
        if any(s in str(rp).lower() or s in str(sp).lower() for s in FORBIDDEN): fail(f"payload path {pid}")
        if sha(rp) != rec["sha256"] or sha(sp) != r["selected_native_input"]["sha256_computed_from_json_metadata"]: fail(f"metadata SHA {pid}")
        rd = json.loads(rp.read_text()); req = rd.get("request", {})
        if rd.get("status") != "completed" or rd.get("returncode") != 0: fail(f"native terminal {pid}")
        idx = r["native_receipt"]["request_input_index"]
        if not isinstance(idx, int) or idx >= len(req.get("input_files", [])) or req["input_files"][idx] != str(sp): fail(f"request input join {pid}")
        launch = rd.get("input_hashes_at_launch", {}).get(str(sp)); after = rd.get("input_hashes_after_run", {}).get(str(sp))
        sel = r["selected_native_input"]
        if launch != after or launch != sel["launch_sha256"] or after != sel["after_sha256"]: fail(f"launch/after pin {pid}")
        declared = req.get("input_sha256", {}).get(str(sp)) if isinstance(req.get("input_sha256"), dict) else None
        if declared is not None and declared != launch: fail(f"request declared SHA {pid}")
        if not (sel["row_physical_case_id_in_source"] or sel["request_physical_case_id_in_source"]): fail(f"case-bound source {pid}")
        if not r.get("source_bound_adapter", "").startswith("actual native receipt request input JSON"): fail(f"owner-only source {pid}")
        src = json.loads(sp.read_text()); values = dict(walk(src))
        for name, info in r["field_provenance"].items():
            if info["json_pointer"] not in values or values[info["json_pointer"]] != info["value"]: fail(f"numeric field pin {pid}/{name}")
        if not r.get("native_condition_role_preserved", {}).get("legacy_typed_scope_not_used_as_numeric_proof"): fail(f"role scope {pid}")
    for fam in ("F4", "F5"):
        proof = d["pairwise_shared_known_field_proof"][fam]
        if proof.get("status") != "PASS" or proof.get("failures"): fail(f"pairwise {fam}")
    print(json.dumps({"status": "PASS", "rows": 96, "families": counts, "F5_unknown_time_cases": sorted(SPECIAL), "unknown_never_counts_as_difference": True}, sort_keys=True))

if __name__ == "__main__":
    main()
