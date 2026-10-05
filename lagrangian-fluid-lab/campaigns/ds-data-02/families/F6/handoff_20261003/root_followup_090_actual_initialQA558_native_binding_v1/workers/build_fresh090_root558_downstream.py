#!/usr/bin/env python3
"""Build F6 fresh090 metadata-only downstream bindings for Root558.

This utility reads only JSON metadata and source request files.  It never opens
BI4/H5/CSV/DAT payloads and never launches a job.  It preserves fresh089 and
records the failed Root555 attempt separately from the corrected Root558
attempt.  A Root558 result is usable only when its receipt is completed/0 and
both producer JSON reports say pass; all other output hashes remain null.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

SCHEMA = "ds02.f6.fresh090.root558-actual-initial-qa-native-binding.v1"
FRESH_ID = "fresh090"
SCOPE_ID = "root_followup_090_actual_initialQA558_native_binding_v1"
OLD_FRESH = "fresh089"
ROOT558_SUFFIX = "initial-native-qa-089-root558"
OLD_QA_MARKERS = (
    "/root_followup_089_stage1_actual_gencase_native_qa_binding_v1/qa/initial-native-qa-binding.json",
    "/root_followup_089_stage1_actual_gencase_native_qa_binding_v1/workers/run_f6_initial_native_qa_stage24_fresh089.py",
)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def dump_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def replace_path(value: str, old: str, new: str) -> str:
    return value.replace(old, new)


def actual_root558(data_f6: Path, case_id: str, request558: dict[str, Any]) -> dict[str, Any]:
    outputs = request558.get("future_outputs") or {}
    attempt_root = Path(str(request558["attempt_root"]))
    receipt = attempt_root / "execution-receipt.json"
    report = Path(str(outputs["per_case_report"]))
    index = Path(str(outputs["initial_native_qa_index"]))
    result: dict[str, Any] = {
        "attempt_id": request558.get("attempt_id"),
        "attempt_root": str(attempt_root),
        "request": None,
        "request_sha256": None,
        "binding": request558.get("binding"),
        "binding_sha256": request558.get("binding_sha256"),
        "worker": request558.get("worker"),
        "worker_sha256": request558.get("worker_sha256"),
        "receipt": str(receipt),
        "report": str(report),
        "index": str(index),
        "receipt_sha256": None,
        "report_sha256": None,
        "index_sha256": None,
        "pass": None,
        "status": "pending_root558_actual_strict_cpu_qa",
        "report_pass": None,
        "index_pass": None,
        "metadata_only": True,
    }
    if not receipt.exists():
        return result
    try:
        rd = load(receipt)
    except (OSError, ValueError):
        result["status"] = "root558_receipt_unreadable"
        return result
    rstatus = rd.get("status")
    rcode = rd.get("returncode")
    result["receipt_status"] = rstatus
    result["receipt_returncode"] = rcode
    result["receipt_sha256"] = sha(receipt)
    if rstatus != "completed" or rcode != 0:
        result["status"] = "root558_failed_or_nonzero"
        return result
    if not report.exists() or not index.exists():
        result["status"] = "root558_completed_missing_result_json"
        return result
    try:
        report_data = load(report)
        index_data = load(index)
    except (OSError, ValueError):
        result["status"] = "root558_result_json_unreadable"
        return result
    report_pass = report_data.get("pass") is True
    index_pass = index_data.get("pass") is True
    result["report_pass"] = report_pass
    result["index_pass"] = index_pass
    result["report_sha256"] = sha(report)
    result["index_sha256"] = sha(index)
    if report_pass and index_pass:
        result["pass"] = True
        result["status"] = "completed0_pass"
    else:
        result["status"] = "completed0_result_not_pass"
    return result


def root555_history(data_f6: Path, case_id: str) -> dict[str, Any]:
    stem = case_id.lower().replace("_", "-")
    attempt = data_f6 / case_id / f"root-stage1-f6-{stem}-initial-native-qa-089-root555"
    receipt = attempt / "execution-receipt.json"
    out: dict[str, Any] = {
        "attempt_id": f"root-stage1-f6-{stem}-initial-native-qa-089-root555",
        "attempt_root": str(attempt),
        "receipt": str(receipt),
        "receipt_sha256": None,
        "status": "not_started",
        "returncode": None,
        "pass": None,
        "used_as_current_qa": False,
        "claim": "historical Root555 attempt only; no PartVTK pass is inferred",
    }
    if not receipt.exists():
        return out
    try:
        rd = load(receipt)
    except (OSError, ValueError):
        out["status"] = "receipt_unreadable"
        return out
    out["status"] = rd.get("status")
    out["returncode"] = rd.get("returncode")
    out["receipt_sha256"] = sha(receipt)
    if rd.get("status") == "completed" and rd.get("returncode") == 0:
        out["claim"] = "historical Root555 completed receipt; no current QA result substitution"
    elif rd.get("status") == "failed":
        out["status"] = "failed_before_partvtk"
        out["claim"] = "historical Root555 failed before PartVTK; preserved and excluded from current QA"
    return out


def add_or_replace_input(d: dict[str, Any], old_markers: tuple[str, ...], paths: list[tuple[str, str, str]]) -> None:
    files = [str(x) for x in d.get("input_files", [])]
    hashes = {str(k): v for k, v in (d.get("input_sha256") or {}).items()}
    sources = {str(k): v for k, v in (d.get("input_hash_sources") or {}).items()}
    for old in list(files):
        if any(marker in old for marker in old_markers):
            files.remove(old)
            hashes.pop(old, None)
            sources.pop(old, None)
    for path, digest, source in paths:
        if path not in files:
            files.append(path)
        hashes[path] = digest
        sources[path] = source
    d["input_files"] = files
    d["input_sha256"] = hashes
    d["input_hash_sources"] = sources


def state0_rebind(src_binding: dict[str, Any], src_request: dict[str, Any], new_pkg: Path, native_paths: dict[str, tuple[str, str]]) -> tuple[dict[str, Any], dict[str, Any]]:
    b = copy.deepcopy(src_binding)
    b["fresh_id"] = FRESH_ID
    b["scope_id"] = SCOPE_ID
    b["status"] = "source_only_disabled_waiting_root230_native_then_state0"
    b["claim_boundary"] = "Disabled future FloatingInfo state-zero corroboration only; Root558 QA and Root230 full241 native must be actual completed/0 first; no visual/Q-N/precision/production result"
    b["native_qualification_requests_dir"] = str(new_pkg / "qualification" / "requests")
    b["native_qualification_request_sha256"] = None
    b["actual_initial_qa_root558_binding"] = str(new_pkg / "qa" / "initial-native-qa-root558-binding.json")
    b["actual_initial_qa_root558_binding_sha256"] = None
    for case in b.get("cases", []):
        cid = str(case["case_id"])
        if cid in native_paths:
            case["native_request"] = native_paths[cid][0]
            case["native_request_sha256"] = native_paths[cid][1]
        case["state0_future_outputs"] = {
            "audit": case.get("state0_future_outputs", {}).get("audit"),
            "audit_sha256": None,
        }
    r = copy.deepcopy(src_request)
    r["fresh_id"] = FRESH_ID
    r["scope_id"] = SCOPE_ID
    r["binding"] = str(new_pkg / "floatinginfo" / "state0-binding.json")
    r["binding_sha256"] = None
    r["status"] = "source_only_disabled_waiting_root230_native_then_state0"
    r["disabled_reason"] = "disabled until all fresh090 Root230 full241 native receipts are terminal completed/0; each FloatingInfo state0 audit must use its own XML/owner/native receipt"
    r["claim_boundary"] = b["claim_boundary"]
    # Rebind only internal native-request and state0-binding references.  The
    # GenCase, owner, XML and official binaries remain the producer sources.
    old_req_dir = str(Path(src_binding["native_qualification_requests_dir"]))
    new_req_dir = str(new_pkg / "qualification" / "requests")
    def remap(path: str) -> str:
        return path.replace(old_req_dir, new_req_dir)
    for key in ("input_files", "future_input_files"):
        if key in r:
            r[key] = [remap(str(x)) if old_req_dir in str(x) else str(x) for x in r[key]]
    for key in ("input_sha256", "future_input_sha256", "input_hash_sources"):
        if key in r and isinstance(r[key], dict):
            r[key] = {remap(str(k)) if old_req_dir in str(k) else str(k): v for k, v in r[key].items()}
    # Replace the old binding path in closure maps.
    old_binding = str(Path(src_binding.get("scope_id", "")))
    old_binding_path = str(Path(str(src_request["binding"])))
    new_binding_path = str(new_pkg / "floatinginfo" / "state0-binding.json")
    for key in ("input_files", "future_input_files"):
        if key in r:
            r[key] = [new_binding_path if str(x) == old_binding_path else x for x in r[key]]
    for key in ("input_sha256", "future_input_sha256", "input_hash_sources"):
        if key in r and isinstance(r[key], dict):
            r[key] = {new_binding_path if str(k) == old_binding_path else k: v for k, v in r[key].items()}
    return b, r


VALIDATOR = r'''#!/usr/bin/env python3
"""Validate fresh090 Root558 QA metadata and disabled native bindings.

Only JSON metadata and source request files are read.  This validator never
opens BI4/H5/CSV/DAT/scientific arrays and never launches a process.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any

OLD_MARKERS = ("root146", "root_stage1_f6_first8", "mechanical-pose-omega-initial-native-qa-089")

def sha(p: Path) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def load(p: Path) -> dict[str,Any]:
    d=json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(d,dict): raise RuntimeError(f"expected object: {p}")
    return d

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--package",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    a=ap.parse_args(); pkg=a.package.resolve()
    binding=load(pkg/"qa/initial-native-qa-root558-binding.json")
    assert binding["case_count"]==24
    requests=sorted((pkg/"qualification/requests").glob("*.json"))
    assert len(requests)==24, len(requests)
    rows=[]; seen=set(); completed=pending=failed=0
    for p in requests:
        d=load(p); cid=str(d["case_id"]); assert cid not in seen; seen.add(cid)
        assert d["disabled"] is True and d["launch"] is False
        assert d["launch_allowed"] is False and d["execution_allowed"] is False
        qa=d["actual_initial_qa"]
        assert qa["attempt_id"].endswith("-089-root558")
        assert qa["request"].endswith("root_stage1_f6_actualGen539_corrected_metadata_native_initial_QA_558/"+cid+"-initial-qa-request.json")
        assert qa["binding"].endswith(cid+"-initial-QA-binding.json")
        assert qa["report"] and qa["receipt"] and qa["index"]
        for value in (qa["request"],qa["binding"],qa["worker"]):
            assert Path(value).exists(), value
        for field in ("report_sha256","receipt_sha256","index_sha256"):
            if qa.get(field) is not None: assert len(str(qa[field]))==64
        text=json.dumps(qa,sort_keys=True)
        assert not any(marker in text for marker in OLD_MARKERS)
        if qa.get("pass") is True: completed+=1
        elif qa.get("status")=="root558_failed_or_nonzero": failed+=1
        else: pending+=1
        rows.append({"case_id":cid,"status":qa.get("status"),"pass":qa.get("pass")})
    assert len(seen)==24
    st=load(pkg/"floatinginfo/state0-binding.json")
    assert st["launch_allowed"] is False and st["execution_allowed"] is False
    assert st["future_hashes_null"] is True
    assert st["particle_v0_policy"] == "V0=0 does not prove zero angular velocity"
    result={"schema":"ds02.f6.fresh090.root558-validation.v1","pass":True,"case_count":24,"completed0_pass":completed,"pending":pending,"root558_failed":failed,"rows":rows,"no_science_payload_read_or_hash":True,"native_solver_started_by_validator":False}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))
    return 0
if __name__ == "__main__": raise SystemExit(main())
'''


def build(out: Path, source089: Path, integration558: Path, data_f6: Path, force: bool) -> None:
    if out.exists():
        if not force:
            raise SystemExit(f"output exists: {out}; pass --force only for a source-only rebuild")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    source_req_dir = source089 / "qualification" / "requests"
    source_requests = sorted(source_req_dir.glob("*.json"))
    if len(source_requests) != 24:
        raise RuntimeError(f"expected 24 fresh089 requests, found {len(source_requests)}")
    source_manifest = source089 / "manifest.json"
    source_binding = source089 / "qa" / "initial-native-qa-binding.json"
    source_state_binding = source089 / "floatinginfo" / "state0-binding.json"
    source_state_request = source089 / "floatinginfo" / "state0-request.json"
    if not all(p.exists() for p in (source_manifest, source_binding, source_state_binding, source_state_request)):
        raise RuntimeError("fresh089 source closure is incomplete")
    # Read Root558 request metadata and derive current output status.  This does
    # not open any producer binary or scientific payload.
    entries: list[dict[str, Any]] = []
    for src in source_requests:
        sd = load(src)
        cid = str(sd["case_id"])
        rp = integration558 / f"{cid}-initial-qa-request.json"
        if not rp.exists():
            raise RuntimeError(f"missing Root558 request for {cid}: {rp}")
        rd = load(rp)
        actual = actual_root558(data_f6, cid, rd)
        actual["request"] = str(rp)
        actual["request_sha256"] = sha(rp)
        hist = root555_history(data_f6, cid)
        entries.append({"case_id": cid, "source_request": src, "source_request_sha256": sha(src), "source": sd, "root558_request": rp, "root558_request_data": rd, "actual": actual, "root555_history": hist})
    scope = out / "metadata"
    qa_dir = out / "qa"
    req_dir = out / "qualification" / "requests"
    float_dir = out / "floatinginfo"
    worker_dir = out / "workers"
    for p in (scope, qa_dir, req_dir, float_dir, worker_dir): p.mkdir(parents=True, exist_ok=True)
    # Minimal source index; no payload names are read beyond producer paths.
    source_index = {
        "schema": "ds02.f6.fresh090.source-fresh089-request-index.v1",
        "source_fresh_id": OLD_FRESH,
        "source_manifest": str(source_manifest),
        "source_manifest_sha256": sha(source_manifest),
        "source_initial_qa_binding": str(source_binding),
        "source_initial_qa_binding_sha256": sha(source_binding),
        "case_count": 24,
        "requests": [{"case_id": e["case_id"], "path": str(e["source_request"]), "sha256": e["source_request_sha256"]} for e in entries],
        "immutable": True,
        "no_science_payload_read_or_hash": True,
    }
    dump(scope / "source-fresh089-request-index.json", source_index)
    # Root558 binding is an output of source metadata inspection and keeps
    # failed Root555 evidence separate from usable completed/0 reports.
    binding_path = qa_dir / "initial-native-qa-root558-binding.json"
    binding = {
        "schema": SCHEMA,
        "family_id": "F6",
        "fresh_id": FRESH_ID,
        "scope_id": SCOPE_ID,
        "source_fresh_id": OLD_FRESH,
        "source_package": str(source089),
        "source_package_sha256": sha(source_manifest),
        "root558_handoff": str(integration558),
        "root558_attempt_suffix": ROOT558_SUFFIX,
        "case_count": 24,
        "actual_gencase_completed0_all24": True,
        "actual_initial_qa_completed0_pass_count": sum(e["actual"].get("pass") is True for e in entries),
        "actual_initial_qa_pending_count": sum(e["actual"].get("pass") is not True and e["actual"].get("status") != "root558_failed_or_nonzero" for e in entries),
        "actual_initial_qa_failed_count": sum(e["actual"].get("status") == "root558_failed_or_nonzero" for e in entries),
        "status": "source_only_disabled",
        "launch_allowed": False,
        "execution_allowed": False,
        "claim_boundary": "Root539 GenCase completed/0 and Root558 QA metadata are bound only per actual completed/0 report; native full241 remains disabled until every case has an actual QA pass; no FloatingInfo/typed/XMF/render/visual/Q-N/precision/production claim",
        "particle_v0_policy": "V0=0 does not prove zero angular velocity; each case still requires later full native FloatingInfo state0 corroboration",
        "mass_semantics": "physical 128 kg, native support 256 kg, and masspart 0.015625 kg remain distinct; no normalization",
        "pose_geometry_policy": "Root558 corrected worker validates the rotated pose and preserves all fresh089 thresholds; no axis-aligned shortcut",
        "historical_root555_excluded": True,
        "no_science_payload_read_or_hash": True,
        "endpoints": [],
    }
    for e in entries:
        a = copy.deepcopy(e["actual"])
        # Never leave a receipt/report hash in the effective field unless the
        # corresponding Root558 JSON metadata is complete/0 and pass=true.
        if a.get("pass") is not True:
            a["pass"] = None
            a["receipt_sha256"] = None
            a["report_sha256"] = None
            a["index_sha256"] = None
            a.pop("receipt_status", None)
            a.pop("receipt_returncode", None)
            a["report_pass"] = None
            a["index_pass"] = None
        binding["endpoints"].append({
            "case_id": e["case_id"],
            "source_native_request": str(e["source_request"]),
            "source_native_request_sha256": e["source_request_sha256"],
            "effective_native_request": str(req_dir / e["source_request"].name),
            "root558_initial_qa_request": a["request"],
            "root558_initial_qa_request_sha256": a["request_sha256"],
            "root558_binding": a["binding"],
            "root558_binding_sha256": a["binding_sha256"],
            "root558_worker": a["worker"],
            "root558_worker_sha256": a["worker_sha256"],
            "actual_initial_qa": a,
            "historical_root555": e["root555_history"],
        })
    dump(binding_path, binding)
    binding_sha = sha(binding_path)
    # Create fresh090 effective disabled native requests.  They retain fresh089
    # Root230 recipe/attempt roots and producer GenCase hashes, but their QA
    # gate points only to Root558.  The fresh089 files are never modified.
    native_paths: dict[str, tuple[str, str]] = {}
    request_objects: list[tuple[Path, dict[str, Any]]] = []
    for e in entries:
        sd = copy.deepcopy(e["source"])
        cid = e["case_id"]
        out_req = req_dir / e["source_request"].name
        # Keep the planned native attempt path/command unchanged; only the
        # source-package identifier and QA dependency are downstream-bound.
        sd["fresh_id"] = FRESH_ID
        sd["scope_id"] = SCOPE_ID
        sd["source_fresh_id"] = OLD_FRESH
        sd["source_request_immutable"] = {"path": str(e["source_request"]), "sha256": e["source_request_sha256"]}
        sd["binding"] = str(binding_path)
        sd["binding_sha256"] = binding_sha
        sd["disabled"] = True
        sd["launch"] = False
        sd["launch_allowed"] = False
        sd["execution_allowed"] = False
        sd["status"] = "source_only_disabled_waiting_root558_initial_qa"
        sd["disabled_reason"] = "fresh090 source-only; enable this unchanged Root230 12 s / 0.05 s / 241-frame native recipe only after the corrected Root558 per-case strict CPU initial QA is completed/0 and pass=true"
        sd["claim_boundary"] = "Root539 GenCase completed/0 plus Root230 native recipe only; Root558 initial QA is a per-case dependency; no native solver, FloatingInfo state0, typed/XMF/render, visual, Q-N, precision, or production result"
        sd["actual_initial_qa"] = copy.deepcopy(e["actual"])
        sd["actual_initial_qa"]["binding"] = str(binding_path)
        sd["actual_initial_qa"]["binding_sha256"] = binding_sha
        if sd["actual_initial_qa"].get("pass") is not True:
            sd["actual_initial_qa"]["pass"] = None
            sd["actual_initial_qa"]["receipt_sha256"] = None
            sd["actual_initial_qa"]["report_sha256"] = None
            sd["actual_initial_qa"]["index_sha256"] = None
            sd["actual_initial_qa"]["report_pass"] = None
            sd["actual_initial_qa"]["index_pass"] = None
            sd["actual_initial_qa"].pop("receipt_status", None)
            sd["actual_initial_qa"].pop("receipt_returncode", None)
        sd["historical_initial_qa_root555"] = e["root555_history"]
        sd["floatinginfo_state0"] = copy.deepcopy(sd.get("floatinginfo_state0", {}))
        sd["floatinginfo_state0"]["status"] = "future_required_after_fresh090_full241_native_completed0"
        # Replace all old QA dependency files with the corrected Root558
        # producer request/binding/worker.  GenCase/XML/BI4 paths and their
        # producer attestations are left unchanged.
        rp = e["root558_request"]
        rb = Path(str(e["root558_request_data"]["binding"]))
        rw = Path(str(e["root558_request_data"]["worker"]))
        additions = [
            (str(rp), sha(rp), "Root558 actual initial-QA request metadata"),
            (str(rb), str(e["root558_request_data"].get("binding_sha256") or sha(rb)), "Root558 actual initial-QA binding metadata"),
            (str(rw), str(e["root558_request_data"].get("worker_sha256") or sha(rw)), "Root558 corrected initial-QA worker source"),
        ]
        add_or_replace_input(sd, OLD_QA_MARKERS, additions)
        sd["worker"] = str(rw)
        sd["worker_sha256"] = additions[2][1]
        # Root230 remains the only native execution entry.  No historical
        # Root146/Root142 qualification entry is introduced here.
        if "root_actual_launch_source" in sd:
            assert "root_stage1_native_home_floor_eight_solver_dispatch_230" in str(sd["root_actual_launch_source"])
        native_paths[cid] = (str(out_req), e["source_request_sha256"])
        request_objects.append((out_req, sd))
    for out_req, obj in request_objects:
        dump(out_req, obj)
    # Update native request hashes in state0 after requests exist.
    native_paths = {cid: (path, sha(Path(path))) for cid, (path, _) in native_paths.items()}
    # Rewrite request only for its own hash-independent fields: state0 carries
    # request hashes, while native requests do not hash themselves.
    for out_req, obj in request_objects:
        # Native request's own effective path is not in its input closure.
        dump(out_req, obj)
    # State0 binding/request are copied as metadata only and point at the new
    # effective requests.  Future native/state0 hashes remain null.
    sb = load(source_state_binding)
    sr = load(source_state_request)
    sb2, sr2 = state0_rebind(sb, sr, out, native_paths)
    state0_binding_path = float_dir / "state0-binding.json"
    state0_request_path = float_dir / "state0-request.json"
    dump(state0_binding_path, sb2)
    state0_sha = sha(state0_binding_path)
    sr2["binding_sha256"] = state0_sha
    # Add exact new state0 binding and effective native requests to closure.
    def update_state0_closure(obj: dict[str, Any]) -> None:
        for key in ("input_files", "future_input_files"):
            if isinstance(obj.get(key), list):
                obj[key] = [str(state0_binding_path) if str(x) == str(source_state_binding) else str(x) for x in obj[key]]
                for cid, (p, digest) in native_paths.items():
                    old = str(source_req_dir / f"{cid}-full241-native-qualification-089.json")
                    obj[key] = [p if str(x) == old else x for x in obj[key]]
        for key in ("input_sha256", "future_input_sha256", "input_hash_sources"):
            if isinstance(obj.get(key), dict):
                n={}
                for k,v in obj[key].items():
                    nk = str(state0_binding_path) if str(k) == str(source_state_binding) else str(k)
                    for cid,(p,digest) in native_paths.items():
                        old=str(source_req_dir / f"{cid}-full241-native-qualification-089.json")
                        if nk == old: nk=p; v=digest if key != "input_hash_sources" else "fresh090 effective native request metadata"
                    n[nk]=v
                obj[key]=n
    update_state0_closure(sr2)
    sr2["input_files"] = list(dict.fromkeys(sr2.get("input_files", [])))
    sr2["future_input_files"] = list(dict.fromkeys(sr2.get("future_input_files", [])))
    dump(state0_request_path, sr2)
    # Attach state0 path/hash to native requests now that it exists.  This is a
    # metadata dependency and does not claim state0 output.
    for out_req, obj in request_objects:
        obj["floatinginfo_state0"]["binding"] = str(state0_binding_path)
        obj["floatinginfo_state0"]["binding_sha256"] = state0_sha
        dump(out_req, obj)
    # A deterministic review record contains only status and JSON metadata
    # hashes; no scientific payload digests are computed here.
    review = {
        "schema": "ds02.f6.fresh090.root558-review.v1",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_fresh089_immutable": True,
        "source_fresh089_manifest_sha256": sha(source_manifest),
        "root555_historical_preserved": True,
        "root558_metadata_worker_preflight_source": str(integration558 / "actual-root-all24-metadata-worker-preflight-review.json"),
        "root558_metadata_worker_preflight_sha256": sha(integration558 / "actual-root-all24-metadata-worker-preflight-review.json"),
        "case_count": 24,
        "completed0_pass": binding["actual_initial_qa_completed0_pass_count"],
        "pending": binding["actual_initial_qa_pending_count"],
        "failed_or_nonzero": binding["actual_initial_qa_failed_count"],
        "qa_result_policy": "Only Root558 receipt completed/0 plus per-case report pass=true and index pass=true is bound as completed0_pass; all other effective hashes are null",
        "native_policy": "Root230 Home-floor live UUID dispatch only; 12 s / 0.05 s / 241 frames; disabled until all per-case QA gates pass",
        "state0_policy": "FloatingInfo state0 remains independent and future; particle V0=0 is not angular proof",
        "mass_policy": "physical 128 kg vs native support 256 kg remain distinct; no rescale",
        "no_science_payload_read_or_hash": True,
        "no_jobs_started_by_source_package": True,
        "endpoints": [{"case_id": e["case_id"], "root558_status": e["actual"].get("status"), "root558_pass": e["actual"].get("pass"), "root555_status": e["root555_history"].get("status")} for e in entries],
    }
    dump(scope / "root558-review.json", review)
    dump_text(worker_dir / "validate_fresh090_root558_binding.py", VALIDATOR)
    (worker_dir / "validate_fresh090_root558_binding.py").chmod(0o755)
    # Include builder source for a later metadata-only refresh, but do not run
    # it as part of a launch path.
    builder_copy = worker_dir / "build_fresh090_root558_downstream.py"
    shutil.copy2(Path(__file__).resolve(), builder_copy)
    builder_copy.chmod(0o755)
    # Fresh090 manifest is intentionally a source-only inventory.  It is written
    # last and excludes self-hashes to avoid self-reference.
    files = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file() and p.name != "manifest.json")
    manifest = {
        "schema": "ds02.f6.fresh090.manifest.v1",
        "fresh_id": FRESH_ID,
        "family_id": "F6",
        "scope_id": SCOPE_ID,
        "source_only": True,
        "no_science_payloads": True,
        "case_count": 24,
        "source_fresh089_immutable": True,
        "root558_completed0_pass_count": binding["actual_initial_qa_completed0_pass_count"],
        "root558_pending_count": binding["actual_initial_qa_pending_count"],
        "root555_failure_preserved": True,
        "claim_boundary": "Metadata binding and disabled Root230 native requests only; no new solver/QA/state0/typed/XMF/render/visual/Q-N/precision/production result is claimed",
        "files": files,
    }
    dump(out / "manifest.json", manifest)
    print(json.dumps({"output": str(out), "case_count":24, "root558_completed0_pass": binding["actual_initial_qa_completed0_pass_count"], "root558_pending": binding["actual_initial_qa_pending_count"], "root555_failed_preserved": binding["actual_initial_qa_failed_count"]}, sort_keys=True))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source089", type=Path, required=True)
    ap.add_argument("--integration558", type=Path, required=True)
    ap.add_argument("--data-f6", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--force", action="store_true")
    a=ap.parse_args()
    build(a.output.resolve(), a.source089.resolve(), a.integration558.resolve(), a.data_f6.resolve(), a.force)
    return 0
if __name__ == "__main__": raise SystemExit(main())
