#!/usr/bin/env python3
"""Build fresh211 from F3 producer-report and native-receipt metadata only."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "metadata/f3-actual-forcing-pairwise-provenance.json"
FRESH209 = Path("/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_209_f6_assigned_f3_f4_f5_normalized_tuple_full144_v1/metadata/f3-f4-f5-normalized-tuples-144.json")
FRESH210 = Path("/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_210_f6_assigned_f3_mother_pitch_running_after_f5_amplitude_supplement_v1/metadata/f3-mother-running-after-f5-amplitude-supplement.json")
FRESH208 = Path("/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_208_f6_assigned_f3_actual_forcing_binding_correction_v1/metadata/f3-actual-forcing-correction.json")
FIELDS = ("drive_amplitude_G", "amplitude_x", "amplitude_y", "omega_y", "phase_y", "tau_ramp")

def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""): h.update(b)
    return h.hexdigest()

def load(p: str | Path) -> Any:
    q = Path(p)
    if q.suffix.lower() != ".json": raise RuntimeError(f"JSON only: {q}")
    return json.loads(q.read_text())

def ref(p: Path, role: str) -> dict[str, Any]:
    if p.suffix.lower() not in {".json", ".xml", ".xmf"}: raise RuntimeError(f"payload ref rejected: {p}")
    return {"role": role, "path": str(p), "exists": p.exists(), "bytes": p.stat().st_size if p.exists() else None, "sha256": sha(p) if p.exists() else None}

def report_for(row: dict[str, Any], receipt: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    candidates = []
    for raw in receipt.get("request", {}).get("input_files", []):
        p = Path(raw)
        if p.name == "prepared-input-report.json" and p.exists():
            z = load(p); candidates.append((p, z))
    exact = [x for x in candidates if x[1].get("physical_case_id") == row.get("physical_case_id")]
    if exact: return exact[0]
    same_case = [x for x in candidates if x[1].get("case_id") == row.get("case_id")]
    if same_case: return same_case[0]
    raise RuntimeError(f"actual producer report missing: {row.get('physical_case_id')}")

def xml_for(receipt: dict[str, Any]) -> Path:
    req = receipt.get("request", {})
    candidates = []
    for raw in [req.get("gencase_prefix")] + list(req.get("command", [])):
        if not isinstance(raw, str): continue
        q = Path(raw if raw.endswith(".xml") else raw + ".xml")
        if q.exists(): candidates.append(q)
    if candidates: return candidates[0]
    for raw in req.get("input_files", []):
        q = Path(raw)
        if q.suffix.lower() == ".xml" and q.exists(): return q
    raise RuntimeError(f"XML metadata missing: {req.get('case_id')}")

def join(receipt: dict[str, Any], p: Path) -> dict[str, Any]:
    launch = receipt.get("input_hashes_at_launch", {})
    after = receipt.get("input_hashes_after_run", {})
    actual = sha(p)
    return {"path": str(p), "metadata_sha256": actual, "launch_sha256": launch.get(str(p)), "after_sha256": after.get(str(p)), "launch_matches_metadata": launch.get(str(p)) == actual, "after_matches_metadata": after.get(str(p)) == actual, "launch_after_equal": launch.get(str(p)) == after.get(str(p))}

def build_row(row: dict[str, Any]) -> dict[str, Any]:
    rp = Path(row["actual_native"]["path"]); receipt = load(rp); req = receipt.get("request", {})
    report_path, report = report_for(row, receipt); transform = report.get("forcing_transform", {}); params = report.get("physical_binding", {}).get("parameters", {})
    xp = xml_for(receipt); launch = receipt.get("input_hashes_at_launch", {}); after = receipt.get("input_hashes_after_run", {})
    output = Path(str(transform.get("output_file", "")))
    numeric = {"drive_amplitude_G": params.get("drive_amplitude_G"), "amplitude_x": transform.get("amplitude_x"), "amplitude_y": transform.get("amplitude_y"), "omega_y": transform.get("omega_y"), "phase_y": transform.get("phase_y"), "tau_ramp": transform.get("tau_ramp")}
    numeric = {k: v for k, v in numeric.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
    status = receipt.get("status"); after_known = bool(after)
    request_binding = req.get("physical_binding", {}).get("parameters", {})
    request_forcing = {
        "drive_amplitude_G": request_binding.get("drive_amplitude_G"),
        "amplitude_x": req.get("nominal_pitch_multiplier", request_binding.get("nominal_pitch_multiplier")),
        "amplitude_y": req.get("transverse_amplitude_m_s2", request_binding.get("transverse_amplitude_m_s2")),
        "omega_y": request_binding.get("transverse_omega_rad_s"),
        "phase_y": request_binding.get("transverse_phase_rad"),
        "tau_ramp": request_binding.get("transverse_ramp_duration_s"),
    }
    request_forcing = {k: v for k, v in request_forcing.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
    report_declared = {"transverse_amplitude_m_s2": report.get("transverse_amplitude_m_s2", params.get("transverse_amplitude_m_s2")), "nominal_pitch_multiplier": report.get("nominal_pitch_multiplier", params.get("nominal_pitch_multiplier"))}
    return {
        "physical_case_id": row["physical_case_id"], "case_id": row["case_id"],
        "native_receipt": ref(rp, "actual_native_execution_receipt"), "native_status": status, "native_returncode": receipt.get("returncode"),
        "producer_report": ref(report_path, "actual_forcing_prepared_input_report"), "producer_report_case_id": report.get("case_id"), "producer_report_physical_case_id": report.get("physical_case_id"),
        "producer_forcing": {"transform": {k: transform.get(k) for k in ("amplitude_x", "amplitude_y", "omega_y", "phase_y", "tau_ramp")}, "physical_binding_parameters": {k: params.get(k) for k in ("drive_amplitude_G", "transverse_amplitude_m_s2", "transverse_omega_rad_s", "transverse_phase_rad", "transverse_ramp_duration_s")}, "report_declarations": report_declared, "report_binding_amplitude_y_matches_transform": report_declared.get("transverse_amplitude_m_s2") == transform.get("amplitude_y")},
        "request_forcing_declaration": request_forcing,
        "request_report_join": {"amplitude_x_matches": request_forcing.get("amplitude_x") == transform.get("amplitude_x"), "amplitude_y_matches": request_forcing.get("amplitude_y") == transform.get("amplitude_y"), "drive_amplitude_matches": request_forcing.get("drive_amplitude_G") == params.get("drive_amplitude_G")},
        "forcing_numeric_fields": numeric,
        "metadata_sha_join": {"producer_report": join(receipt, report_path), "native_xml": join(receipt, xp)},
        "producer_output": {"path": str(output), "producer_attested_sha256": transform.get("output_sha256"), "launch_sha256": launch.get(str(output)), "after_sha256": after.get(str(output)), "launch_matches_producer": launch.get(str(output)) == transform.get("output_sha256"), "after_matches_producer": None if str(output) not in after else after.get(str(output)) == transform.get("output_sha256"), "payload_opened_or_hashed": False},
        "running_role": {"after_state": "unknown" if status == "running" and not after_known else "available", "original_status_rewritten": False, "downstream_recovery_is_separate": status == "running"},
    }

def pairwise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for left, right in itertools.combinations(rows, 2):
        shared = [k for k in FIELDS if k in left["forcing_numeric_fields"] and k in right["forcing_numeric_fields"]]
        diff = [k for k in shared if left["forcing_numeric_fields"][k] != right["forcing_numeric_fields"][k]]
        out.append({"left": left["physical_case_id"], "right": right["physical_case_id"], "shared_known_fields": shared, "different_fields": diff, "all_shared_fields_equal": not diff})
    return out

def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--output", type=Path, default=OUT); args = ap.parse_args()
    if args.output.exists(): raise SystemExit(f"refusing to overwrite {args.output}")
    source = load(FRESH209); correction = load(FRESH208); rows = [build_row(r) for r in source["cases"]["F3"]]; rows.sort(key=lambda r: r["physical_case_id"])
    pairs = pairwise(rows); groups = {}
    keyed = {}
    for r in rows: keyed.setdefault(tuple(r["forcing_numeric_fields"].get(k) for k in FIELDS), []).append(r["physical_case_id"])
    groups = {str(k): v for k, v in keyed.items() if len(v) > 1}
    main_proof = correction["main_external_proof"]["path"]
    request_mismatch = [r["physical_case_id"] for r in rows if not all(r["request_report_join"].values())]
    report_mismatch = [r["physical_case_id"] for r in rows if not r["producer_forcing"]["report_binding_amplitude_y_matches_transform"]]
    result = {"schema": "ds02.f6.fresh211.f3-actual-forcing-pairwise-provenance.v1", "created_at_utc": datetime.now(timezone.utc).isoformat(), "model": "gpt-5.6-luna", "reasoning_effort": "max", "inputs": {"fresh208": ref(FRESH208, "immutable_fresh208_endpoint_forcing_correction"), "root1456": ref(Path(main_proof), "Root1456_actual_endpoint_forcing_and_stale_binding_proof"), "fresh209": ref(FRESH209, "immutable_fresh209_144_tuple_audit"), "fresh210": ref(FRESH210, "immutable_fresh210_running_after_role_supplement")}, "source_boundaries": {"json_xml_only": True, "scientific_payloads_read_or_hashed": False, "payloads": ["CSV", "BI4", "H5", "DAT", "VTK", "PNG"], "jobs_started": False, "shared_state_modified": False, "case_credit": 0, "Q_N": False, "Q_E": False}, "numeric_comparison_policy": {"fields": list(FIELDS), "only_shared_known_numeric_fields_compared": True, "producer_report_is_authoritative": True, "request_and_owner_values_are_provenance_only": True, "identifier_pitch_resolution_time_view_excluded": True}, "rows": rows, "pairwise_comparisons": pairs, "summary": {"rows": len(rows), "pair_count": len(pairs), "pairs_with_known_difference": sum(1 for p in pairs if p["different_fields"]), "pairs_equal_on_all_shared_fields": sum(1 for p in pairs if p["all_shared_fields_equal"]), "forcing_numeric_collision_groups": groups, "running_rows_preserved": [r["physical_case_id"] for r in rows if r["native_status"] == "running"], "producer_report_binding_mismatches": report_mismatch, "request_vs_producer_provenance_mismatches": request_mismatch}}
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(args.output), "rows": len(rows), "pairs": len(pairs), "collisions": len(groups)}, sort_keys=True))

if __name__ == "__main__": main()
