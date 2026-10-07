#!/usr/bin/env python3
"""Build a metadata-only normalized tuple audit for F3/F4/F5 (144 rows)."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

AUDIT = Path("/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_194_f3_full336_physical_distinctness_role_audit_v1/metadata/full336-physical-distinctness-audit.json")
FORCING = Path("/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_208_f6_assigned_f3_actual_forcing_binding_correction_v1/metadata/f3-actual-forcing-correction.json")
OUT = Path(__file__).resolve().parents[1] / "metadata/f3-f4-f5-normalized-tuples-144.json"

F5_EXPLICIT_BINDINGS = {
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_A080": "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_109_stage1_f5_c082s1_actual_bed_full801_disabled_v1/bindings/A080-physical-binding.json",
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_A120": "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_109_stage1_f5_c082s1_actual_bed_full801_disabled_v1/bindings/A120-physical-binding.json",
}

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def load(path: str | Path) -> Any:
    p = Path(path)
    if p.suffix.lower() != ".json":
        raise RuntimeError(f"only JSON metadata may be loaded: {p}")
    return json.loads(p.read_text())

def ref(path: str | Path, role: str) -> dict[str, Any]:
    p = Path(path)
    return {"role": role, "path": str(p), "exists": p.exists(), "bytes": p.stat().st_size if p.exists() else None, "sha256": sha(p) if p.exists() else None}

def canon(x: Any) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def digest(x: Any) -> str:
    return hashlib.sha256(canon(x).encode()).hexdigest()

def walk(x: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, v
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)

def case(audit: dict[str, Any], physical_id: str) -> dict[str, Any]:
    for c in audit.get("cases", []):
        if c.get("physical_case_id") == physical_id:
            return c
    raise KeyError(physical_id)

def find_ref(c: dict[str, Any], predicate) -> str | None:
    for x in c.get("source_metadata", {}).get("metadata_refs", []):
        p = x.get("path")
        if p and Path(p).exists() and predicate(x):
            return p
    return None

def native_receipt_path(c: dict[str, Any]) -> str:
    p = find_ref(c, lambda x: x.get("key") in {"native_request_scope.evidence.receipt", "native_request_scope.actual_native_receipt.path"} and x.get("path", "").endswith("execution-receipt.json"))
    if not p:
        p = find_ref(c, lambda x: "/families/" in x.get("path", "") and "native" in x.get("path", "") and x.get("path", "").endswith("execution-receipt.json"))
    if not p:
        raise RuntimeError(f"native receipt missing for {c.get('physical_case_id')}")
    return p

def owner_path(c: dict[str, Any]) -> str | None:
    return find_ref(c, lambda x: "/owners/" in x.get("path", "") and x.get("path", "").endswith(".json"))

def receipt_meta(path: str) -> dict[str, Any]:
    d = load(path); req = d.get("request", {}) if isinstance(d.get("request"), dict) else {}
    launch = d.get("input_hashes_at_launch", {}) if isinstance(d.get("input_hashes_at_launch"), dict) else {}
    after = d.get("input_hashes_after_run", {}) if isinstance(d.get("input_hashes_after_run"), dict) else {}
    metadata = []
    for p in sorted(set(launch) | set(after)):
        if Path(p).suffix.lower() in {".json", ".xml", ".xmf"}:
            metadata.append({"path": p, "launch": launch.get(p), "after": after.get(p), "equal": launch.get(p) == after.get(p)})
    return {"path": path, "sha256": sha(Path(path)), "status": d.get("status"), "returncode": d.get("returncode"), "request_sha256": d.get("request_sha256"), "request_case_id": req.get("case_id"), "request_physical_case_id": req.get("physical_case_id"), "request_condition_sha256": req.get("physical_condition_sha256"), "metadata_input_join": metadata, "metadata_input_count": len(metadata), "metadata_input_mismatch_count": sum(1 for x in metadata if not x["equal"]), "scientific_payload_policy": "only producer-attested metadata was used; payload was not read or hashed"}

def first_field(rows: Any, suffixes: set[str]) -> Any:
    if not isinstance(rows, list): return None
    for row in rows:
        if isinstance(row, dict) and str(row.get("field", "")).split(".")[-1] in suffixes:
            return row.get("value")
    return None

def geometry_from_tuple(tv: dict[str, Any]) -> Any:
    rows = tv.get("geometry", []) if isinstance(tv, dict) else []
    return next((r.get("value") for r in rows if isinstance(r, dict) and isinstance(r.get("value"), dict)), None)

def tuple_f3(c: dict[str, Any]) -> dict[str, Any]:
    tv = c.get("family_physical_tuple", {}).get("tuple_value", {})
    forcing = tv.get("pitch_and_forcing", []) if isinstance(tv, dict) else []
    return {"drive_amplitude_G": first_field(forcing, {"drive_amplitude_G"}), "nominal_pitch_multiplier": first_field(forcing, {"nominal_pitch_multiplier", "pitch_multiplier"}), "transverse_amplitude_m_s2": first_field(forcing, {"transverse_amplitude_m_s2", "transverse_amplitude"}), "transverse_omega_rad_s": first_field(forcing, {"transverse_omega_rad_s"}), "transverse_phase_rad": first_field(forcing, {"transverse_phase_rad"}), "transverse_ramp_duration_s": first_field(forcing, {"transverse_ramp_duration_s"}), "geometry": geometry_from_tuple(tv)}

def tuple_f4(c: dict[str, Any]) -> dict[str, Any]:
    tv = c.get("family_physical_tuple", {}).get("tuple_value", {})
    drops = tv.get("drop_parameters", []) if isinstance(tv, dict) else []
    vals = {}
    for row in drops:
        if isinstance(row, dict):
            n = str(row.get("field", "")).split(".")[-1]
            if n in {"gap_m", "x_offset_m", "y_offset_m", "speed_m_per_s"} and n not in vals: vals[n] = row.get("value")
    vel = next((r.get("value") for r in tv.get("initial_velocity", []) if isinstance(r, dict) and isinstance(r.get("value"), dict)), None)
    return {"gap_m": vals.get("gap_m"), "x_offset_m": vals.get("x_offset_m"), "y_offset_m": vals.get("y_offset_m"), "speed_m_per_s": vals.get("speed_m_per_s"), "initial_velocity": vel, "geometry": geometry_from_tuple(tv)}

def binding_path_for_f5(physical_id: str) -> str | None:
    suffix = physical_id.split("_C082S1_")[-1]
    if suffix in {"A080", "A120"}: return F5_EXPLICIT_BINDINGS[physical_id]
    p = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_125_stage1_f5_c082s1_full801_native_qualification_disabled_v1/bindings") / f"{suffix}-physical-binding.json"
    return str(p) if p.exists() else None

def tuple_f5(c: dict[str, Any], physical_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    p = binding_path_for_f5(physical_id)
    evidence = []
    if p:
        b = load(p); params = b.get("parameters", {}) if isinstance(b.get("parameters"), dict) else {}; motion = params.get("piston_motion", {}) if isinstance(params.get("piston_motion"), dict) else {}
        t = {"amplitude_scale": motion.get("amplitude_scale", b.get("amplitude_scale")), "time_scale": motion.get("time_scale", b.get("time_scale")), "geometry": {"fluid_box_m": params.get("fluid_box_m"), "bed_profile_lower_xz_m": params.get("bed_profile_lower_xz_m"), "bed_profile_upper_xz_m": params.get("bed_profile_upper_xz_m"), "bed_extrusion_y_bounds_m": params.get("bed_extrusion_y_bounds_m"), "pointref_m": params.get("pointref_m"), "bed_representation": params.get("bed_representation")}}
        evidence.append(ref(p, "explicit_physical_binding")); return t, evidence, "explicit_binding"
    tv = c.get("family_physical_tuple", {}).get("tuple_value", {}); motion = tv.get("motion", []) if isinstance(tv, dict) else []
    t = {"amplitude_scale": first_field(motion, {"amplitude_scale"}), "time_scale": first_field(motion, {"time_scale"}), "geometry": geometry_from_tuple(tv)}
    op = owner_path(c)
    if op: evidence.append(ref(op, "owner_physical_binding"))
    return t, evidence, "owner_tuple"

def forcing_override(physical_id: str, forcing: dict[str, Any]) -> dict[str, Any] | None:
    for c in forcing.get("cases", []):
        if c.get("physical_case_id") == physical_id:
            t = c.get("actual_forcing_tuple", {}); tx = c.get("producer_report", {}).get("forcing_transform", {}); return {"drive_amplitude_G": tx.get("amplitude_x"), "nominal_pitch_multiplier": None, "transverse_amplitude_m_s2": t.get("transverse_amplitude_m_s2"), "transverse_omega_rad_s": t.get("transverse_omega_rad_s"), "transverse_phase_rad": t.get("phase_rad"), "transverse_ramp_duration_s": t.get("tau_ramp_s")}
    return None

def build_row(family: str, c: dict[str, Any], forcing: dict[str, Any]) -> dict[str, Any]:
    pid = c["physical_case_id"]; op = owner_path(c); evidence = []
    if op: evidence.append(ref(op, "owner_physical_binding"))
    rp = native_receipt_path(c); actual = receipt_meta(rp); req_pid = actual.get("request_physical_case_id")
    if family == "F3":
        tup = forcing_override(pid, forcing) or tuple_f3(c); source_role = "actual_forcing_producer" if pid in {x["physical_case_id"] for x in forcing.get("cases", [])} else "owner_tuple"; status = "PASS_ACTUAL_FORCING_JOIN" if source_role == "actual_forcing_producer" else ("PASS_OWNER_TUPLE" if c.get("family_physical_tuple_status") == "PASS_CASE_BOUND_PHYSICAL_TUPLE" else "UNCERTAIN_PITCH_FIELD_ABSENT")
        if source_role == "actual_forcing_producer": evidence.append(ref(FORCING, "fresh208_actual_forcing_correction"))
    elif family == "F4":
        tup = tuple_f4(c); source_role = "owner_tuple"; status = "PASS_OWNER_TUPLE" if c.get("family_physical_tuple_status") == "PASS_CASE_BOUND_PHYSICAL_TUPLE" else "UNCERTAIN"
    else:
        tup, extra, source_role = tuple_f5(c, pid); evidence.extend(extra); status = "PASS_EXPLICIT_OR_OWNER_TUPLE" if tup.get("amplitude_scale") is not None else "UNCERTAIN_MOTION_FIELD_ABSENT"
    evidence.append(ref(rp, "actual_native_execution_receipt"))
    identity_status = "MATCH" if req_pid == pid else ("REQUEST_PHYSICAL_ID_ABSENT" if req_pid is None else "REQUEST_PHYSICAL_ID_ALIAS_DIFFERENT")
    tuple_digest_allowed = (family == "F5" and tup.get("amplitude_scale") is not None) or (family != "F5" and all(v is not None for k,v in tup.items() if k != "geometry"))
    return {"family_id": family, "physical_case_id": pid, "case_id": c.get("case_id"), "status": status, "normalized_tuple": tup, "normalized_tuple_sha256": digest(tup) if tuple_digest_allowed else None, "source_role": source_role, "source_evidence": evidence, "actual_native": actual, "request_identity": {"request_physical_case_id": req_pid, "identity_status": identity_status, "matches_row_physical_case_id": req_pid == pid, "request_case_id": actual.get("request_case_id")}, "draft_status": c.get("family_physical_tuple_status"), "identifier_tokens_not_used_as_tuple": True, "resolution_time_view_not_used_as_tuple": True}

def main() -> None:
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,default=OUT); args=ap.parse_args()
    if args.output.exists(): raise SystemExit(f"refusing to overwrite {args.output}")
    audit=load(AUDIT); forcing=load(FORCING); rows={fam:[] for fam in ["F3","F4","F5"]}
    for c in audit["cases"]:
        if c.get("family_id") in rows: rows[c["family_id"]].append(build_row(c["family_id"],c,forcing))
    for fam in rows: rows[fam].sort(key=lambda r:r["physical_case_id"])
    collisions={}
    for fam, rs in rows.items():
        by={}
        for r in rs:
            if r["normalized_tuple_sha256"]: by.setdefault(r["normalized_tuple_sha256"],[]).append(r["physical_case_id"])
        collisions[fam]={k:v for k,v in by.items() if len(v)>1}
    result={"schema":"ds02.f6.fresh209.f3-f4-f5.normalized-tuples-144.v1","created_at_utc":datetime.now(timezone.utc).isoformat(),"model":"gpt-5.6-luna","reasoning_effort":"max","source_boundaries":{"scientific_payloads_read_or_hashed":False,"payloads":["BI4","H5","CSV","DAT","VTK","PNG"],"jobs_started":False,"shared_state_modified":False,"case_credit":0,"Q_N":False,"Q_E":False},"inputs":{"fresh194":ref(AUDIT,"fresh194_full336_audit"),"fresh208":ref(FORCING,"fresh208_actual_forcing_correction")},"normalization":{"F3":"drive/forcing values, nominal pitch only when explicit, geometry; no IDs/paths/resolution/time window/view","F4":"gap/offset/speed/initial velocity/geometry; no IDs/paths/resolution/time window/view","F5":"amplitude_scale/time_scale and geometry; no IDs/paths/resolution/time window/view"},"cases":rows,"collision_groups":collisions,"summary":{fam:{"count":len(rs),"status_counts":{status:sum(1 for r in rs if r['status']==status) for status in sorted({r['status'] for r in rs})},"missing_or_uncertain":[r['physical_case_id'] for r in rs if r['status'].startswith('UNCERTAIN')]} for fam,rs in rows.items()}}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+'\n');print(json.dumps({"output":str(args.output),"counts":{k:len(v) for k,v in rows.items()},"collisions":{k:len(v) for k,v in collisions.items()}},sort_keys=True))

if __name__=='__main__': main()
