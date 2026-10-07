#!/usr/bin/env python3
"""Small, direct metadata-only F1/F6 numeric uniqueness/pin validator."""
import argparse, hashlib, json, math, sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
INDEX = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_full336_actual336_user_delivery_direct_XMF_N3_times_navigation_physical_difference_and_goal_audit_unproven_1451/DS-DATA-02-ACTUAL-USER-DELIVERY-INDEX.json")
BASE_XML = "F6_ANGULAR_RELEASE_DP025.xml"
BAD = {".bi4", ".h5", ".csv", ".dat", ".vtk", ".xmf"}
def die(s): raise RuntimeError(s)
def num(x):
    try: x = float(x)
    except (TypeError, ValueError): return None
    return x if math.isfinite(x) else None
def vec(x):
    return [num(v) for v in x] if isinstance(x, list) and len(x) == 3 and all(num(v) is not None for v in x) else None
def j(path):
    p = Path(path)
    if p.suffix.lower() != ".json" or p.suffix.lower() in BAD: die(f"refused metadata path: {p}")
    return json.loads(p.read_text(encoding="utf-8"))
def pathof(x):
    return Path(x) if isinstance(x, str) else Path(x["path"]) if isinstance(x, dict) and isinstance(x.get("path"), str) else None
def find_pb(x):
    if isinstance(x, dict) and isinstance(x.get("physical_binding"), dict): return x["physical_binding"]
    values = x.values() if isinstance(x, dict) else x if isinstance(x, list) else ()
    return next((found for v in values if (found := find_pb(v)) is not None), None)
def metadata_source(q): return next((p for p in [pathof(q.get(k)) for k in ("actual_continuum_binding", "binding", "owner_provenance", "owner")] + [pathof(x) for x in q.get("input_bindings", [])] if p and p.suffix.lower() == ".json" and p.is_file() and isinstance(find_pb(j(p)), dict)), None)
def native_path(family, row):
    refs = row.get("actual_native_condition_observation", {}).get("observations", []) if family == "F1" else row.get("primary_refs", {}).get("native", [])
    return next((p for item in refs if (p := pathof(item.get("receipt") if family == "F1" else item)) and p.name == "execution-receipt.json"), None) or die(f"native receipt missing: {row.get('physical_case_id')}")
def pin(path, receipt, source):
    launch, after = receipt.get("input_hashes_at_launch"), receipt.get("input_hashes_after_run")
    current = hashlib.sha256(Path(source).read_bytes()).hexdigest(); key = str(source)
    return {"receipt_path": str(path), "source_path": key, "source_sha256": current, "source_sha_matches_launch_after": isinstance(launch, dict) and isinstance(after, dict) and launch.get(key) == current and after.get(key) == current,
            "completed0": receipt.get("status") == "completed" and receipt.get("returncode") == 0, "launch_after_equal": isinstance(launch, dict) and isinstance(after, dict) and launch == after,
            "launch_sha_key_count": len(launch) if isinstance(launch, dict) else None,
            "after_sha_key_count": len(after) if isinstance(after, dict) else None}
def f1_numeric(row, q, receipt):
    sp = pathof(q.get("source_plan")); source = None; doc_path = None
    if sp:
        plan = j(sp); grid = plan.get("grid", {})
        depth, velocity = grid.get("nominal_physical_fluid_depth_m"), plan.get("initial_velocity_declaration_m_per_s") or plan.get("axis", {}).get("velocity_m_per_s") or plan.get("source_plan_condition", {}).get("initial_velocity_m_per_s")
        source = {"path": str(sp), "fields": ["grid.nominal_physical_fluid_depth_m", "initial_velocity_declaration_m_per_s"]}
    else:
        doc_path = metadata_source(q)
        doc = j(doc_path) if doc_path else q
        pb = find_pb(doc) or find_pb(q) or {}
        depth = q.get("parameter_tuple", {}).get("fluid_depth_m") if isinstance(q.get("parameter_tuple"), dict) else None
        if depth is None: depth = pb.get("parameters", {}).get("fluid_depth_m")
        state = pb.get("initial_state", {}) if isinstance(pb.get("initial_state"), dict) else {}
        velocity = q.get("motion", {}).get("initial_velocities_m_per_s", {}).get("fluid") if isinstance(q.get("motion"), dict) else None
        if velocity is None: velocity = state.get("velocities_m_per_s", {}).get("fluid") if isinstance(state.get("velocities_m_per_s"), dict) else None
        if velocity is None: velocity = pb.get("initialization", {}).get("velocity_m_s")
        if depth is None: depth = q.get("geometry", {}).get("fluid_reservoir", {}).get("size_m", [None, None, None])[2]
        if depth is None:
            g, fr = pb.get("geometry", {}), pb.get("geometry", {}).get("fluid_reservoir"); size = fr.get("size_m") if isinstance(fr, dict) else g.get("fluid_reservoir_size_m"); depth = size[2] if isinstance(size, list) and len(size) == 3 else None
        source = {"path": str(doc_path or receipt), "fields": ["parameter_tuple.fluid_depth_m/physical_binding.parameters.fluid_depth_m", "motion.initial_velocities_m_per_s.fluid or physical_binding.initial_state.velocities_m_per_s.fluid"]}
    if num(depth) is None or vec(velocity) is None:
        doc_path = doc_path or metadata_source(q)
        if doc_path:
            pb = find_pb(j(doc_path)) or {}
            depth = depth if num(depth) is not None else pb.get("parameters", {}).get("fluid_depth_m")
            velocity = velocity or pb.get("initialization", {}).get("velocity_m_s") or pb.get("initial_state", {}).get("velocities_m_per_s", {}).get("fluid")
    vv = vec(velocity)
    if num(depth) is None or vv is None: die(f"F1 numeric field missing: {row['physical_case_id']}")
    return {"fluid_depth_m": num(depth), "initial_fluid_vx_m_s": vv[0]}, source
def baseline_omega(q):
    p = Path(q.get("gencase_xml", ""))
    if p.name != BASE_XML: die(f"unexpected F6 baseline XML: {p}")
    root = ET.parse(p).getroot(); node = root.find("./casedef/floatings/floating/angularvelini")
    if node is None: die("baseline angularvelini missing")
    values = vec([node.get(a) for a in ("x", "y", "z")])
    if values is None: die("baseline angular vector invalid")
    return values, {"path": str(p), "fields": ["casedef.floatings.floating.angularvelini@x/y/z"]}
def f6_numeric(row, q, receipt):
    if row["physical_case_id"] == "F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE":
        value, source = baseline_omega(q); present = False
    else:
        owner = pathof(q.get("canonical_owner")) or die(f"F6 canonical owner missing: {row['physical_case_id']}")
        pb = find_pb(j(owner)) or {}; value = vec(pb.get("parameters", {}).get("initial_angular_velocity_rad_s")) or vec(q.get("initial_angular_velocity_rad_s")); source = {"path": str(owner), "fields": ["physical_binding.parameters.initial_angular_velocity_rad_s"]}; present = q.get("initial_angular_velocity_rad_s") is not None
    if value is None: die(f"F6 angular vector missing: {row['physical_case_id']}")
    return {"initial_angular_velocity_rad_s": value}, source, present
def build(index_path):
    idx = j(index_path); rows = []
    for family in ("F1", "F6"):
        product = j(idx["families"][family]["product"]["path"]); key = "cases" if family == "F1" else "rows"
        for row in product[key]:
            rp = native_path(family, row); receipt = j(rp); q = receipt.get("request", {})
            if family == "F1": numeric, source = f1_numeric(row, q, rp); presence = None
            else: numeric, source, present = f6_numeric(row, q, rp); presence = {"request_initial_angular_velocity_rad_s": present, "baseline_xml_request_field_absent": not present if row["physical_case_id"].endswith("OMEGA_BASELINE") else None}
            rows.append({"family_id": family, "case_ref": row["physical_case_id"], "numeric_tuple": numeric, "numeric_source": source, "native_pin": pin(rp, receipt, source["path"]), "request_field_presence": presence})
    groups = defaultdict(list)
    for row in rows: values = [x for value in row["numeric_tuple"].values() for x in (value if isinstance(value, list) else [value])]; groups[(row["family_id"], tuple(values))].append(row["case_ref"])
    duplicates = [{"family_id": k[0], "numeric_tuple": list(k[1]), "case_refs": v} for k, v in groups.items() if len(v) > 1]
    return {"schema": "ds02.fresh233.numeric-tuple-pin-audit.v1", "basis": {"F1": ["fluid_depth_m", "initial_fluid_vx_m_s"], "F6": ["initial_angular_velocity_rad_s"], "ignored_for_comparison": ["case_ref", "path", "hash", "geometry_tree", "yaw"]}, "rows": rows, "duplicates": duplicates, "summary": {"rows": len(rows), "F1": sum(r["family_id"] == "F1" for r in rows), "F6": sum(r["family_id"] == "F6" for r in rows), "native_pin_verified": sum(all(r["native_pin"].get(k) for k in ("completed0", "launch_after_equal", "source_sha_matches_launch_after")) for r in rows), "duplicate_groups": len(duplicates)}}
def validate(report):
    rows = report.get("rows", []); errors = []
    if len(rows) != 96 or sum(r.get("family_id") == "F1" for r in rows) != 48 or sum(r.get("family_id") == "F6" for r in rows) != 48: errors.append("expected F1=48,F6=48")
    if report.get("duplicates"): errors.append("numeric tuple duplicate groups present")
    for r in rows:
        if not all(r.get("native_pin", {}).get(k) for k in ("completed0", "launch_after_equal", "source_sha_matches_launch_after")): errors.append(f"native pin failed: {r.get('case_ref')}")
        p = r.get("numeric_source", {}).get("path", "")
        if Path(p).suffix.lower() not in {".json", ".xml"} or Path(p).suffix.lower() in BAD: errors.append(f"bad metadata source: {p}")
    if report.get("summary", {}).get("native_pin_verified") != 96: errors.append("pin summary mismatch")
    return errors
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--index", type=Path, default=INDEX); ap.add_argument("--output", type=Path); ap.add_argument("--validate", type=Path); a = ap.parse_args()
    report = json.loads(a.validate.read_text()) if a.validate else build(a.index)
    errors = validate(report)
    if errors:
        for e in errors: print("ERROR:", e, file=sys.stderr)
        return 1
    if a.output: a.output.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
    elif not a.validate: print(json.dumps(report, indent=2, sort_keys=True))
    print("VALID fresh233: F1=48, F6=48, numeric duplicates=0, native pins=96", file=sys.stderr)
    return 0
if __name__ == "__main__": raise SystemExit(main())
