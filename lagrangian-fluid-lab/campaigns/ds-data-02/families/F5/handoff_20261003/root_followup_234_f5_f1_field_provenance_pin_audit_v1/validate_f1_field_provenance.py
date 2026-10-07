#!/usr/bin/env python3
"""F1-only metadata field provenance and native receipt pin audit."""
import argparse, hashlib, json, math, sys
from collections import defaultdict
from pathlib import Path
INDEX = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_full336_actual336_user_delivery_direct_XMF_N3_times_navigation_physical_difference_and_goal_audit_unproven_1451/DS-DATA-02-ACTUAL-USER-DELIVERY-INDEX.json")
DEPTH = ("/physical_binding/geometry/fluid_reservoir_size_m/2", "/physical_binding/parameters/fluid_depth_m", "/physical_binding/geometry/fluid_reservoir/size_m/2")
VX = ("/initial_velocity_declaration_m_per_s/0", "/axis/velocity_m_per_s/0", "/source_plan_condition/initial_velocity_m_per_s/0", "/physical_binding/initialization/velocity_m_s/0", "/physical_binding/initial_state/velocities_m_per_s/fluid/0", "/physical_binding/initial_state/velocity_control/velocity_m_per_s/0")
def die(s): raise RuntimeError(s)
def pathof(x): return Path(x) if isinstance(x, str) else Path(x["path"]) if isinstance(x, dict) and isinstance(x.get("path"), str) else None
def load(p):
    p = Path(p)
    if p.suffix.lower() != ".json": die(f"non-JSON source refused: {p}")
    return json.loads(p.read_text(encoding="utf-8"))
def at(doc, pointer):
    cur = doc
    for token in pointer.strip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        cur = cur[int(token)] if isinstance(cur, list) else cur[token]
    return cur
def finite(v):
    try: v = float(v)
    except (TypeError, ValueError): return None
    return v if math.isfinite(v) else None
def docs(q):
    out = []
    for k in ("actual_continuum_binding", "binding", "owner_provenance", "owner", "canonical_owner"):
        p = pathof(q.get(k))
        if p: out.append(p)
    out += [p for p in (pathof(x) for x in q.get("input_bindings", [])) if p and p.suffix.lower() == ".json"]
    seen = set()
    return [p for p in out if not (str(p) in seen or seen.add(str(p)))]
def field(paths, pointers):
    for p in paths:
        if not p.is_file() or p.suffix.lower() != ".json": continue
        d = load(p)
        for pointer in pointers:
            try: value = finite(at(d, pointer))
            except (KeyError, IndexError, TypeError, ValueError): continue
            if value is not None: return {"path": str(p), "json_pointer": pointer, "value": value}
    return None
def pin_field(f, receipt):
    p = Path(f["path"]); current = hashlib.sha256(p.read_bytes()).hexdigest(); key = str(p)
    launch, after = receipt.get("input_hashes_at_launch"), receipt.get("input_hashes_after_run")
    f["sha256"] = current; f["source_sha_match_launch_after"] = isinstance(launch, dict) and isinstance(after, dict) and launch.get(key) == current and after.get(key) == current
    return f
def native_pin(path, receipt):
    launch, after = receipt.get("input_hashes_at_launch"), receipt.get("input_hashes_after_run")
    return {"receipt_path": str(path), "completed0": receipt.get("status") == "completed" and receipt.get("returncode") == 0, "launch_after_equal": isinstance(launch, dict) and isinstance(after, dict) and launch == after, "launch_sha_key_count": len(launch) if isinstance(launch, dict) else None, "after_sha_key_count": len(after) if isinstance(after, dict) else None}
def receipt_path(row):
    for item in row.get("actual_native_condition_observation", {}).get("observations", []):
        p = pathof(item.get("receipt"))
        if p and p.name == "execution-receipt.json": return p
    die(f"native receipt missing: {row.get('physical_case_id')}")
def build(index_path):
    index, rows = load(index_path), []
    product = load(index["families"]["F1"]["product"]["path"])
    for item in product["cases"]:
        rp = receipt_path(item); receipt = load(rp); q = receipt.get("request", {}); sp = pathof(q.get("source_plan")); source_docs = [sp] if sp else docs(q)
        depth = field(source_docs, ("/grid/nominal_physical_fluid_depth_m",)) if sp else None
        if depth is None: depth = field(docs(q), DEPTH)
        vx = field([sp], VX[:3]) if sp else field(source_docs, VX[3:])
        if depth is None or vx is None: die(f"F1 field provenance missing: {item['physical_case_id']}")
        depth, vx = pin_field(depth, receipt), pin_field(vx, receipt)
        rows.append({"family_id": "F1", "case_ref": item["physical_case_id"], "numeric_tuple": {"fluid_depth_m": depth["value"], "initial_fluid_vx_m_s": vx["value"]}, "field_provenance": {"fluid_depth_m": depth, "initial_fluid_vx_m_s": vx}, "native_pin": native_pin(rp, receipt)})
    groups = defaultdict(list)
    for row in rows: groups[(row["numeric_tuple"]["fluid_depth_m"], row["numeric_tuple"]["initial_fluid_vx_m_s"])].append(row["case_ref"])
    dup = [{"numeric_tuple": list(k), "case_refs": v} for k, v in groups.items() if len(v) > 1]
    return {"schema": "ds02.fresh234.f1-field-provenance-pin-audit.v1", "basis": ["fluid_depth_m", "initial_fluid_vx_m_s"], "ignored_for_comparison": ["case_ref", "path", "sha256", "geometry_tree", "yaw"], "rows": rows, "duplicates": dup, "summary": {"rows": len(rows), "numeric_duplicate_groups": len(dup), "native_pins_verified": sum(r["native_pin"]["completed0"] and r["native_pin"]["launch_after_equal"] for r in rows), "field_pins_verified": sum(all(r["field_provenance"][k]["source_sha_match_launch_after"] for k in ("fluid_depth_m", "initial_fluid_vx_m_s")) for r in rows) * 2}}
def validate(report):
    rows, errors = report.get("rows", []), []
    if len(rows) != 48: errors.append("expected 48 F1 rows")
    if report.get("duplicates"): errors.append("numeric tuple duplicate groups present")
    for row in rows:
        if row.get("family_id") != "F1" or not (row.get("native_pin", {}).get("completed0") and row.get("native_pin", {}).get("launch_after_equal")): errors.append(f"native pin failed: {row.get('case_ref')}")
        for name in ("fluid_depth_m", "initial_fluid_vx_m_s"):
            f = row.get("field_provenance", {}).get(name, {})
            if not f.get("path") or not f.get("json_pointer") or not f.get("source_sha_match_launch_after"): errors.append(f"field pin failed: {row.get('case_ref')}:{name}")
    if report.get("summary", {}).get("native_pins_verified") != 48 or report.get("summary", {}).get("field_pins_verified") != 96: errors.append("pin summary mismatch")
    return errors
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--index", type=Path, default=INDEX); ap.add_argument("--output", type=Path); ap.add_argument("--validate", type=Path); a = ap.parse_args(); report = json.loads(a.validate.read_text()) if a.validate else build(a.index); errors = validate(report)
    if errors:
        for e in errors: print("ERROR:", e, file=sys.stderr)
        return 1
    if a.output: a.output.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
    print("VALID fresh234: F1=48, numeric duplicates=0, field pins=96, native pins=48", file=sys.stderr); return 0
if __name__ == "__main__": raise SystemExit(main())
