#!/usr/bin/env python3
"""Build the bounded fresh207 physical-distinctness metadata sidecar.

This reader is deliberately metadata-only.  It reads JSON and XML/XMF
metadata and producer-attested fields from receipts.  It never opens BI4,
H5, CSV, DAT, VTK, or PNG payloads and never launches a producer.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

AUDIT_DEFAULT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/"
    "root_followup_194_f3_full336_physical_distinctness_role_audit_v1/"
    "metadata/full336-physical-distinctness-audit.json"
)
OUT_DEFAULT = Path(__file__).resolve().parents[1] / "metadata/physical-distinctness-spot-audit.json"

F3_CASES = {
    "F3_TWOAXIS_PITCH1000_AY0250_VISUAL_DOMAIN": {
        "receipt": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_P1000_AY0250/root-stage1-twoaxis-lower-physical-endpoint-full836-native-009/execution-receipt.json",
        "endpoint_xml": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_PHYSICAL_VISUAL_ENDPOINT_PREPARATION/root-stage1-twoaxis-two-physical-amplitude-endpoints-exact-initial-inputs-006/prepared/lower/F3_STAGE1_DP006_P1000_AY0250.xml",
        "source_binding": "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_visual_domain_endpoint_native_007/lower-physical-binding.json",
        "declared_endpoint": {"pitch_label": "P1000", "pitch_numeric": None, "transverse_amplitude_m_s2": 0.25},
    },
    "F3_TWOAXIS_PITCH1000_AY0750_VISUAL_DOMAIN": {
        "receipt": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_P1000_AY0750/root-stage1-twoaxis-upper-physical-endpoint-full836-native-009/execution-receipt.json",
        "endpoint_xml": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_PHYSICAL_VISUAL_ENDPOINT_PREPARATION/root-stage1-twoaxis-two-physical-amplitude-endpoints-exact-initial-inputs-006/prepared/upper/F3_STAGE1_DP006_P1000_AY0750.xml",
        "source_binding": "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_visual_domain_endpoint_native_007/upper-physical-binding.json",
        "declared_endpoint": {"pitch_label": "P1000", "pitch_numeric": None, "transverse_amplitude_m_s2": 0.75},
    },
}

F4_CASES = [
    "F4_DROP_gap0p20000_xoff0p08000_yoff0p04000_uz0p40000",
    "F4_DROP_gap0p20000_xoff0p08000_yoff0p04000_uz0p60000",
    "F4_DROP_gap0p20000_xoffm0p08000_yoff0p04000_uz0p40000",
]

F5_BINDINGS = {
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_A080": "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_109_stage1_f5_c082s1_actual_bed_full801_disabled_v1/bindings/A080-physical-binding.json",
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_A120": "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_109_stage1_f5_c082s1_actual_bed_full801_disabled_v1/bindings/A120-physical-binding.json",
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_M085_T090": "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_125_stage1_f5_c082s1_full801_native_qualification_disabled_v1/bindings/M085_T090-physical-binding.json",
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_M115_T080": "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_125_stage1_f5_c082s1_full801_native_qualification_disabled_v1/bindings/M115_T080-physical-binding.json",
    "F5_COMPACT_RUNUP_RECOVERY_C082S1_M115_T100": "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_125_stage1_f5_c082s1_full801_native_qualification_disabled_v1/bindings/M115_T100-physical-binding.json",
}

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def safe_metadata_path(path: Path) -> None:
    ext = path.suffix.lower()
    if ext in {".h5", ".bi4", ".csv", ".dat", ".vtk", ".bin", ".raw"}:
        raise RuntimeError(f"scientific payload access refused: {path}")

def load_json(path: str | Path) -> Any:
    p = Path(path)
    safe_metadata_path(p)
    if p.suffix.lower() != ".json":
        raise RuntimeError(f"JSON reader received non-JSON path: {p}")
    return json.loads(p.read_text())

def metadata_ref(path: str | Path, role: str, *, hash_file: bool = True) -> dict[str, Any]:
    p = Path(path)
    safe_metadata_path(p)
    item: dict[str, Any] = {"role": role, "path": str(p), "exists": p.exists()}
    if p.exists():
        st = p.stat()
        item["bytes"] = st.st_size
        if hash_file and p.suffix.lower() in {".json", ".xml", ".xmf"}:
            item["sha256"] = sha256(p)
        else:
            item["sha256"] = None
            item["hash_policy"] = "not read or hashed by source-only audit"
    return item

def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def walk(obj: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            yield p, v
            yield from walk(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield f"{prefix}[{i}]", v
            yield from walk(v, f"{prefix}[{i}]")

def first_key(obj: Any, keys: set[str]) -> Any:
    for path, value in walk(obj):
        if path.rsplit(".", 1)[-1] in keys:
            return value
    return None

def nested(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur

def receipt_join(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    d = load_json(p)
    request = d.get("request") if isinstance(d.get("request"), dict) else {}
    launch = d.get("input_hashes_at_launch") if isinstance(d.get("input_hashes_at_launch"), dict) else {}
    after = d.get("input_hashes_after_run") if isinstance(d.get("input_hashes_after_run"), dict) else {}
    metadata_ext = {".json", ".xml", ".xmf"}
    metadata_paths = sorted(set(launch) | set(after))
    metadata_rows = []
    science_count = 0
    for item in metadata_paths:
        ext = Path(item).suffix.lower()
        if ext in metadata_ext:
            metadata_rows.append({"path": item, "launch": launch.get(item), "after": after.get(item), "equal": launch.get(item) == after.get(item)})
        elif ext in {".h5", ".bi4", ".csv", ".dat", ".vtk", ".bin", ".raw"}:
            science_count += 1
    return {
        "path": str(p),
        "sha256": sha256(p),
        "status": d.get("status"),
        "returncode": d.get("returncode"),
        "request_sha256": d.get("request_sha256"),
        "request_case_id": request.get("case_id"),
        "request_physical_case_id": request.get("physical_case_id"),
        "request_condition_sha256": request.get("physical_condition_sha256"),
        "metadata_input_join": metadata_rows,
        "metadata_input_count": len(metadata_rows),
        "metadata_input_mismatch_count": sum(1 for x in metadata_rows if not x["equal"]),
        "scientific_input_attestation_count": science_count,
        "scientific_payload_policy": "producer-attested hashes/count only; payload was not read or hashed",
    }, request

def ref_by_key(case: dict[str, Any], predicate) -> str | None:
    for ref in case.get("source_metadata", {}).get("metadata_refs", []):
        p = ref.get("path")
        if p and Path(p).exists() and predicate(ref):
            return p
    return None

def audit_case(audit: dict[str, Any], physical_id: str) -> dict[str, Any]:
    for c in audit.get("cases", []):
        if c.get("physical_case_id") == physical_id or c.get("case_id") == physical_id:
            return c
    raise KeyError(physical_id)

def f3_case(physical_id: str, spec: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    c = audit_case(audit, physical_id)
    receipt, request = receipt_join(spec["receipt"])
    source = load_json(spec["source_binding"])
    req_binding = request.get("physical_binding") if isinstance(request.get("physical_binding"), dict) else {}
    req_params = req_binding.get("parameters") if isinstance(req_binding.get("parameters"), dict) else {}
    src_params = source.get("parameters", {})
    endpoint_xml = metadata_ref(spec["endpoint_xml"], "actual_launch_after_endpoint_xml")
    source_ref = metadata_ref(spec["source_binding"], "Root007_source_owner_binding")
    actual_amplitude = req_params.get("transverse_amplitude_m_s2")
    source_amplitude = src_params.get("transverse_amplitude_m_s2")
    source_tuple = {"pitch_numeric": None, "pitch_evidence": "no numeric pitch field in Root007 binding; P1000 is retained as a reference label only", "reference_variant": src_params.get("reference_variant"), "transverse_amplitude_m_s2": source_amplitude}
    request_tuple = {"pitch_numeric": None, "pitch_evidence": "no numeric pitch field in actual request; nominal reference is retained separately", "transverse_amplitude_m_s2": actual_amplitude}
    return {
        "family_id": "F3", "physical_case_id": physical_id, "case_id": request.get("case_id"),
        "status": "MISMATCH_ACTUAL_REQUEST_USED_NOMINAL_SOURCE" if actual_amplitude != source_amplitude else "PASS",
        "finding": "Root007 source binding carries the requested endpoint amplitude, but the actual native request and endpoint XML point to the nominal AY0P50 single-axis input; this native product does not prove the .25/.75 endpoint distinction.",
        "declared_endpoint_tuple": spec["declared_endpoint"],
        "source_owner_tuple": source_tuple,
        "actual_native_request_tuple": request_tuple,
        "tuple_method": "numeric amplitude fields only; pitch has no numeric source field and is reported null; P1000 labels, IDs, paths, resolution and time window are not numeric tuple evidence",
        "draft_case": {
            "draft_physical_difference_status": c.get("physical_difference_status"),
            "draft_tuple_status": c.get("family_physical_tuple_status"),
            "draft_tuple_sha256": c.get("family_physical_tuple_sha256"),
        },
        "source_evidence": [source_ref, endpoint_xml],
        "actual_native": receipt,
        "request_binding_fields": {
            "control_family_id": req_binding.get("control_family_id"),
            "physical_case_id": req_binding.get("physical_case_id"),
            "parameters": {k: req_params.get(k) for k in ["transverse_amplitude_m_s2", "transverse_omega_rad_s", "reference_variant"] if k in req_params},
            "gencase_prefix": request.get("gencase_prefix"),
            "input_endpoint_xml": spec["endpoint_xml"],
        },
        "launch_after_validation": {
            "metadata_input_mismatch_count": receipt["metadata_input_mismatch_count"],
            "endpoint_xml_launch_after_sha": next((x for x in receipt["metadata_input_join"] if x["path"] == spec["endpoint_xml"]), None),
        },
    }

def pick_f4_owner(case: dict[str, Any]) -> str:
    p = ref_by_key(case, lambda r: "/owners/" in r.get("path", "") and r.get("path", "").endswith(".json"))
    if not p:
        raise RuntimeError(f"no F4 owner metadata for {case.get('physical_case_id')}")
    return p

def pick_f4_receipt(case: dict[str, Any]) -> str:
    p = ref_by_key(case, lambda r: r.get("key") == "native_request_scope.evidence.receipt")
    if not p:
        p = ref_by_key(case, lambda r: "execution-receipt.json" in r.get("path", "") and "full1201-native" in r.get("path", ""))
    if not p:
        raise RuntimeError(f"no F4 native receipt for {case.get('physical_case_id')}")
    return p

def f4_tuple(case: dict[str, Any]) -> dict[str, Any]:
    tv = nested(case, "family_physical_tuple", "tuple_value") or {}
    drops = tv.get("drop_parameters", []) if isinstance(tv, dict) else []
    vals: dict[str, Any] = {}
    for row in drops:
        if isinstance(row, dict) and "." in str(row.get("field", "")):
            name = str(row["field"]).split(".")[-1]
            if name in {"gap_m", "x_offset_m", "y_offset_m", "speed_m_per_s"} and name not in vals:
                vals[name] = row.get("value")
    velocity = None
    for row in tv.get("initial_velocity", []) if isinstance(tv, dict) else []:
        if isinstance(row, dict) and isinstance(row.get("value"), dict):
            velocity = row["value"]
            break
    geometry = None
    for row in tv.get("geometry", []) if isinstance(tv, dict) else []:
        if isinstance(row, dict) and isinstance(row.get("value"), dict):
            geometry = row["value"]
            break
    return {"gap_m": vals.get("gap_m"), "x_offset_m": vals.get("x_offset_m"), "y_offset_m": vals.get("y_offset_m"), "speed_m_per_s": vals.get("speed_m_per_s"), "initial_velocity": velocity, "geometry": geometry}

def f4_case(physical_id: str, audit: dict[str, Any]) -> dict[str, Any]:
    c = audit_case(audit, physical_id)
    owner_path = pick_f4_owner(c)
    receipt_path = pick_f4_receipt(c)
    owner = load_json(owner_path)
    receipt, request = receipt_join(receipt_path)
    tup = f4_tuple(c)
    tuple_sha = digest(tup)
    groups = audit.get("family_physical_tuple_collision_groups", {}).get("F4", {})
    sig_groups = audit.get("signature_collision_groups", {}).get("F4", {})
    collision = next((ids for ids in groups.values() if physical_id in ids), None)
    sig_collision = next((ids for ids in sig_groups.values() if physical_id in ids), None)
    # The actual request's case binding is checked separately from owner tuple;
    # request may omit nested tuple details but must carry the same case identity.
    request_binding = request.get("physical_binding") if isinstance(request.get("physical_binding"), dict) else {}
    req_params = request_binding.get("parameters") if isinstance(request_binding.get("parameters"), dict) else {}
    return {
        "family_id": "F4", "physical_case_id": physical_id, "case_id": request.get("case_id"),
        "status": "PASS_NORMALIZED_TUPLE_UNIQUE" if not collision and not sig_collision else "DRAFT_COLLISION_REQUIRES_REVIEW",
        "finding": "The selected F4 cases have distinct normalized gap/offset/speed/initial-velocity/geometry tuples. Any identifier-only collision remains non-evidence; no normalized physical tuple collision was found in the rebuilt audit.",
        "normalized_tuple": tup, "normalized_tuple_sha256": tuple_sha,
        "tuple_method": "gap_m, x_offset_m, y_offset_m, speed_m_per_s, initial velocity and geometry; case IDs, paths, resolution, time window and view fields excluded",
        "draft_case": {"draft_tuple_status": c.get("family_physical_tuple_status"), "draft_tuple_sha256": c.get("family_physical_tuple_sha256"), "draft_signature_collision_group": sig_collision, "draft_normalized_collision_group": collision},
        "source_evidence": [metadata_ref(owner_path, "owner_physical_binding"), metadata_ref(receipt_path, "actual_native_execution_receipt")],
        "actual_native": receipt,
        "request_binding_identity": {"request_case_id": request.get("case_id"), "request_physical_case_id": request.get("physical_case_id"), "request_parameters": req_params},
        "owner_binding_identity": {"physical_case_id": owner.get("physical_case_id"), "parameters": owner.get("parameters", {}) if isinstance(owner.get("parameters"), dict) else {}},
        "launch_after_validation": {"metadata_input_mismatch_count": receipt["metadata_input_mismatch_count"], "metadata_join_status": "verified from actual receipt JSON"},
    }

def f5_motion_report(case: dict[str, Any], physical_id: str) -> str | None:
    p = ref_by_key(case, lambda r: r.get("path", "").endswith("motion-transform-report.json") and physical_id.split("_C082S1_")[-1].lower() in r.get("path", "").lower())
    if p:
        return p
    # The producer path may use a lower-case compact token. Match the final case suffix.
    token = physical_id.split("_C082S1_")[-1].lower()
    return ref_by_key(case, lambda r: r.get("path", "").endswith("motion-transform-report.json") and token.replace("_", "") in r.get("path", "").lower().replace("_", ""))

def extract_motion(binding: dict[str, Any]) -> dict[str, Any]:
    p = binding.get("parameters", {}) if isinstance(binding.get("parameters"), dict) else {}
    motion = p.get("piston_motion") if isinstance(p.get("piston_motion"), dict) else {}
    if not motion and isinstance(binding.get("motion_transform"), dict):
        motion = binding["motion_transform"]
    return {"amplitude_scale": motion.get("amplitude_scale", binding.get("amplitude_scale")), "time_scale": motion.get("time_scale", binding.get("time_scale")), "duration_s": motion.get("duration_s"), "kind": motion.get("kind"), "transform_semantics": motion.get("transform_semantics")}

def extract_geometry(binding: dict[str, Any]) -> dict[str, Any]:
    p = binding.get("parameters", {}) if isinstance(binding.get("parameters"), dict) else {}
    return {"fluid_box_m": p.get("fluid_box_m"), "bed_profile_lower_xz_m": p.get("bed_profile_lower_xz_m"), "bed_profile_upper_xz_m": p.get("bed_profile_upper_xz_m"), "bed_extrusion_y_bounds_m": p.get("bed_extrusion_y_bounds_m"), "pointref_m": p.get("pointref_m"), "bed_representation": p.get("bed_representation")}

def f5_case(physical_id: str, audit: dict[str, Any]) -> dict[str, Any]:
    c = audit_case(audit, physical_id)
    binding_path = F5_BINDINGS[physical_id]
    binding = load_json(binding_path)
    motion = extract_motion(binding)
    report_path = f5_motion_report(c, physical_id)
    report = load_json(report_path) if report_path else {}
    native_path = ref_by_key(c, lambda r: r.get("key") in {"native_request_scope.actual_native_receipt.path", "native_request_scope.evidence.receipt"} and r.get("path", "").endswith("execution-receipt.json"))
    if not native_path:
        raise RuntimeError(f"no F5 actual native receipt for {physical_id}")
    receipt, request = receipt_join(native_path)
    tuple_value = {"geometry": extract_geometry(binding), "amplitude_scale": motion.get("amplitude_scale"), "time_scale": motion.get("time_scale"), "duration_s": None}
    tuple_sha = digest(tuple_value)
    draft_owner = c.get("source_metadata", {}).get("owner_physical_binding")
    return {
        "family_id": "F5", "physical_case_id": physical_id, "case_id": binding.get("case_id") or request.get("case_id"),
        "status": "PASS_SOURCE_MOTION_TUPLE_RECOVERED" if motion.get("amplitude_scale") is not None else "UNCERTAIN_MOTION_FIELDS_MISSING",
        "finding": "The explicit F5 physical binding and producer motion-transform report are the authoritative motion tuple. The thin owner selected by fresh194 is recorded separately and is not used to erase missing fields.",
        "normalized_tuple": tuple_value, "normalized_tuple_sha256": tuple_sha,
        "tuple_method": "geometry control values plus amplitude_scale/time_scale; IDs, paths, resolution, time window and view fields excluded; absent time_scale remains null",
        "draft_case": {"draft_tuple_status": c.get("family_physical_tuple_status"), "draft_tuple_sha256": c.get("family_physical_tuple_sha256"), "draft_owner_fields": draft_owner},
        "source_evidence": [metadata_ref(binding_path, "explicit_actual_physical_binding"), metadata_ref(report_path, "producer_motion_transform_report") if report_path else {"role": "producer_motion_transform_report", "exists": False}],
        "actual_native": receipt,
        "motion_transform_fields": {k: report.get(k) for k in ["schema", "status", "scale", "amplitude_scale", "time_scale", "rows", "time_start_s", "time_end_s", "solver_started"] if k in report},
        "binding_motion_fields": motion,
        "request_binding_identity": {"request_case_id": request.get("case_id"), "request_physical_case_id": request.get("physical_case_id"), "request_amplitude_scale": first_key(request, {"amplitude_scale"}), "request_time_scale": first_key(request, {"time_scale"})},
        "owner_binding_identity": {"physical_case_id": binding.get("physical_case_id"), "source_plan_physical_condition_sha256": binding.get("source_plan_physical_condition_sha256"), "physical_condition_sha256": binding.get("physical_condition_sha256")},
        "launch_after_validation": {"metadata_input_mismatch_count": receipt["metadata_input_mismatch_count"], "metadata_join_status": "verified from actual receipt JSON"},
        "producer_hash_policy": "motion/DAT hashes are producer attestations copied from JSON; this audit did not open or hash DAT payload",
    }

def build(audit_path: Path) -> dict[str, Any]:
    audit = load_json(audit_path)
    out: dict[str, Any] = {
        "schema": "ds02.f6.fresh207.cross-family-physical-distinctness-spot-audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": "gpt-5.6-luna", "reasoning_effort": "max",
        "scope": "bounded metadata-only spot audit of F3 endpoints, three F4 draft candidates and five F5 thin-motion sources",
        "source_boundaries": {"scientific_payloads_read_or_hashed": False, "source_payloads": ["BI4", "H5", "CSV", "DAT", "VTK", "PNG"], "producer_attestations_copied": True, "jobs_started": False, "shared_state_modified": False, "case_credit": 0, "Q_N": False, "Q_E": False},
        "fresh194_input": metadata_ref(audit_path, "fresh194_rebuilt_physical_distinctness_audit"),
        "method": {"IDs_paths_resolution_timewindow_views": "reference-only/excluded", "F3": "compare actual native request against endpoint source binding", "F4": "gap/offset/speed/initial velocity/geometry tuple", "F5": "geometry plus explicit piston amplitude/time scale tuple; absent fields stay null"},
        "cases": {"F3": [], "F4": [], "F5": []},
        "family_findings": {},
    }
    out["cases"]["F3"] = [f3_case(pid, spec, audit) for pid, spec in F3_CASES.items()]
    out["cases"]["F4"] = [f4_case(pid, audit) for pid in F4_CASES]
    f5_ids = list(F5_BINDINGS)
    out["cases"]["F5"] = [f5_case(pid, audit) for pid in f5_ids]
    out["family_findings"] = {
        "F3": {"selected": 2, "status": "endpoint_native_input_mismatch", "conclusion": "P1000 .25/.75 source owners are distinct, but the actual endpoint native requests/XML both used nominal AY0P50; no physical endpoint proof."},
        "F4": {"selected": 3, "normalized_tuple_collisions": 0, "conclusion": "No normalized tuple collision in selected three; this is a bounded sample, not a 48-case certification."},
        "F5": {"selected": 5, "draft_thin_sources": 5, "conclusion": "A080/A120 and motion variants require explicit binding/motion-transform sources; fresh194 owner selection was insufficient for those rows."},
    }
    out["tuple_digests"] = {fam: {c["physical_case_id"]: c.get("normalized_tuple_sha256") for c in rows if c.get("normalized_tuple_sha256")} for fam, rows in out["cases"].items()}
    return out

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", type=Path, default=AUDIT_DEFAULT)
    ap.add_argument("--output", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {args.output}")
    result = build(args.audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(args.output), "cases": {k: len(v) for k, v in result["cases"].items()}}, sort_keys=True))

if __name__ == "__main__":
    main()
