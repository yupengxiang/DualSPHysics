#!/usr/bin/env python3
"""Metadata-only validator for the fresh198 running-render preflight.

It reads only JSON metadata and /proc process metadata. XML/log references are
stat-only. It never opens or hashes H5, BI4, IBI4, CSV, DAT, VTK, VTU, or PVTU
payloads and never signals or launches a process.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
FORBIDDEN = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M092_T095_NEXT34"
PHYSICAL = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M092_T095"

def fail(msg: str) -> None:
    raise SystemExit(f"fresh198 validation failed: {msg}")

def read_json(path: Path, label: str):
    if path.suffix.lower() != ".json": fail(f"non-JSON read {label}: {path}")
    if not path.is_file(): fail(f"missing {label}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))

def check_proc(info: dict, label: str) -> dict:
    pid = info.get("pid")
    if not isinstance(pid, int): fail(f"{label} has no PID")
    stat = Path(f"/proc/{pid}/stat")
    observed = {"pid": pid, "present": stat.exists()}
    if stat.exists():
        fields = stat.read_text().split()
        observed["state"] = fields[2] if len(fields) > 2 else None
        observed["start_ticks"] = int(fields[21]) if len(fields) > 21 else None
    expected_ticks = info.get("start_ticks")
    if expected_ticks is not None and observed.get("start_ticks") != expected_ticks:
        fail(f"{label} PID/start_ticks changed or is absent: {observed} expected {expected_ticks}")
    return observed

def main() -> None:
    pre = read_json(PKG / "metadata/preflight.json", "preflight")
    if pre.get("schema") != "ds02.f6.fresh198.f5.m092t095.preflight.v1": fail("schema mismatch")
    if pre.get("case_id") != CASE or pre.get("physical_case_id") != PHYSICAL: fail("case identity mismatch")
    if pre.get("state") != "WAITING_FOR_TERMINAL_RENDER_AND_MAIN_QI": fail("preflight is not the recorded running boundary")
    if pre.get("visual_review_started") is not False or pre.get("published_png_refs") is not None or pre.get("main_qi") is not None: fail("preflight contains premature visual/QI evidence")
    if pre.get("credit_boundary") != {"case_credit": 0, "QN": 0, "QE": 0, "numeric_precision_accepted": False}: fail("credit boundary changed")
    expected = pre.get("expected") or {}
    if expected.get("frames") != 801 or expected.get("particles") != 194427 or expected.get("contacts") != 34 or expected.get("keys") != 9: fail("expected metadata contract changed")
    roles = pre.get("roles")
    if not isinstance(roles, list) or not roles: fail("role observations missing")
    role_by = {r.get("role"): r for r in roles if isinstance(r, dict)}
    for role in ("bed_execution_receipt", "native_execution_receipt", "typed_execution_receipt", "xmf_execution_receipt"):
        r = role_by.get(role)
        if not r or r.get("schema") != "ds02.execution-receipt.v1" or r.get("status") != "completed" or r.get("returncode") != 0: fail(f"upstream role not completed/0: {role}")
    render = role_by.get("render_execution_receipt")
    if not render or render.get("schema") != "ds02.execution-receipt.v1" or render.get("status") != "running" or render.get("returncode") is not None: fail("original1136 render boundary changed")
    req = role_by.get("render_request")
    if not req or req.get("case_id") != CASE or req.get("physical_case_id") != PHYSICAL or req.get("expected_frames") != 801 or req.get("expected_particles") != 194427: fail("render request identity/count contract mismatch")
    wrapper = role_by.get("render_wrapper")
    if not wrapper or wrapper.get("case_id") != CASE or wrapper.get("physical_case_id") != PHYSICAL: fail("render wrapper identity mismatch")
    if not isinstance(req.get("input_closure"), dict) or req["input_closure"].get("keyset_equal") is not True: fail("render request input closure not closed")
    proc = pre.get("process_observation") or {}
    check_proc(proc.get("controller") or {}, "controller")
    check_proc(proc.get("render_worker") or {}, "render worker")
    if proc.get("render_receipt_status") != "running" or proc.get("render_receipt_returncode_field_present") is not False: fail("render process observation is no longer running boundary")
    for ref in pre.get("stat_only_refs") or []:
        if ref.get("role") in {"xmf_xml_metadata", "source_definition_metadata", "render_stdout"} and ref.get("content_read_or_hashed") is not False: fail("stat-only reference was read/hashed")
    for item in (read_json(PKG / "metadata/role-inputs.json", "role inputs").get("refs") or {}).values():
        if Path(item.get("path", "")).suffix.lower() in FORBIDDEN: fail("scientific payload reference entered package role inputs")
    print(json.dumps({"status":"PASS","state":pre["state"],"case_id":CASE,"physical_case_id":PHYSICAL,"render_status":render["status"],"upstream_roles_terminal":True,"visual_review_started":False,"main_qi":None,"case_credit":0}, sort_keys=True))
if __name__ == "__main__": main()
