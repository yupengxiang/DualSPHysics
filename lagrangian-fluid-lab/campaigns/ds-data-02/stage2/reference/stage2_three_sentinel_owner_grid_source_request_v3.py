#!/usr/bin/env python3
"""Build the source-only owner-grid manifest/request for F2-S2, F3-S1, F5-S1.

The builder hashes only bounded XML/JSON/CSV/motion inputs.  It emits future
GenCase-only support requests; no payload output path is treated as an input
and no executable is launched.  The only permitted change in each three-grid
ladder is definition@dp.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys
from pathlib import Path
from typing import Any

SCHEMA = "ds02.stage2.three-sentinel.owner-grid-source-manifest.v3"
REQUEST_SCHEMA = "ds02.request.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
SMALL_CAP = 10 * 1024 * 1024
PAYLOAD_SUFFIXES = {".bi4",".vtk",".h5",".hdf5",".part",".hdf"}
REPO = Path(__file__).resolve().parents[5]
REF = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DEFAULT_STATUS = REF / "stage2_fourteen_source_status_v3.json"
DEFAULT_AUDIT = REF / "stage2_fourteen_source_control_audit_v5.json"
DEFAULT_BOUNDS = REF / "stage2_continuum_geometry_bounds_v1.json"
# This is a small source manifest carrying the already-established SHA for the
# large F3 acceleration file.  It is read as metadata only; the 14.9 MB CSV is
# always deferred to the parent reservation/worker.
DECLARED_INPUT_MANIFEST = REF / "stage2_sentinel_spatial_preflight_inputs_v2/manifest.json"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"
CANDIDATE_ROOTS = {
    "F2-S2": REF / "stage2_sentinel_spatial_preflight_inputs_v1/F2_S2",
    "F3-S1": REF / "stage2_sentinel_spatial_preflight_inputs_v1/F3_S1",
    "F5-S1": REF / "stage2_remaining_sentinel_spatial_preflight_inputs_v1/F5_S1",
}
GRID_LABELS = ("original", "coarse", "fine")

class BuildFailure(RuntimeError):
    pass

def _stat(path: Path) -> dict[str,int]:
    s=path.stat()
    return {"device":int(s.st_dev),"inode":int(s.st_ino),"bytes":int(s.st_size),
            "mtime_ns":int(s.st_mtime_ns),"ctime_ns":int(s.st_ctime_ns)}

def _record(path: Path, label: str, *, read: bool = True) -> dict[str,Any]:
    path=path.expanduser().absolute()
    if path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise BuildFailure(f"{label} is forbidden payload: {path}")
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not regular non-symlink file: {path}")
    st=_stat(path)
    if st["bytes"] > SMALL_CAP:
        raise BuildFailure(f"{label} exceeds bounded source cap: {path}")
    if read:
        raw=path.read_bytes()
        st2=_stat(path)
        if st != st2 or len(raw) != st["bytes"]:
            raise BuildFailure(f"{label} changed during bounded read: {path}")
        digest=hashlib.sha256(raw).hexdigest()
    else:
        digest=None
    return {"path":str(path),"sha256":digest,"stat_after":st,
            "read_by_builder":read,"scope":"bounded_small_source_metadata"}

def _deferred_record(path: Path, label: str, expected_sha: str | None = None) -> dict[str, Any]:
    """Bind a forcing file by path/stat and defer content hashing to parent.

    The parent must establish the first reservation-time SHA and repeat the
    stat/hash after the guarded worker.  A SHA from the small source manifest
    is retained when available, but it is never recomputed in this builder.
    """
    path = path.expanduser().absolute()
    if path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise BuildFailure(f"{label} is forbidden payload: {path}")
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not regular non-symlink file: {path}")
    st = _stat(path)
    digest = expected_sha if isinstance(expected_sha, str) and len(expected_sha) == 64 else "PARENT_AFTER_RESERVATION_SHA_REQUIRED"
    return {"path": str(path), "sha256": digest, "hash_status": "DECLARED_SMALL_MANIFEST" if digest != "PARENT_AFTER_RESERVATION_SHA_REQUIRED" else "PARENT_AFTER_RESERVATION_REQUIRED",
            "stat_before": st, "stat_after": st, "read_by_builder": False,
            "scope": "deferred_forcing_after_parent_reservation",
            "parent_after_reservation_sha_required": True,
            "payload_read_by_builder": False}

def _declared_sha_map(value: Any) -> dict[str, str]:
    """Collect exact path/SHA pairs from a small metadata manifest."""
    found: dict[str, str] = {}
    def visit(node: Any) -> None:
        if isinstance(node, dict):
            path = node.get("path")
            sha = node.get("sha256")
            if isinstance(path, str) and isinstance(sha, str) and len(sha) == 64:
                found[str(Path(path).expanduser().absolute())] = sha.lower()
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
    return found

def _proof_bindings(status: dict[str, Any], static_record: Any) -> list[dict[str, Any]]:
    """Bind every evidence proof referenced by the exact 14-row status card."""
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    rows = status.get("sentinels")
    if not isinstance(rows, list) or len(rows) != 14:
        raise BuildFailure("status card must contain exactly 14 sentinel rows")
    for row in rows:
        sid = row.get("sentinel_id") if isinstance(row, dict) else None
        evidence = row.get("evidence", []) if isinstance(row, dict) else []
        if not isinstance(sid, str) or not isinstance(evidence, list):
            raise BuildFailure("malformed 14-sentinel proof row")
        if not evidence:
            raise BuildFailure(f"{sid} has no exact proof binding")
        row_paths: list[str] = []
        for item in evidence:
            file = item.get("file") if isinstance(item, dict) else None
            path_value = file.get("path") if isinstance(file, dict) else None
            declared_sha = file.get("sha256") if isinstance(file, dict) else None
            if not isinstance(path_value, str) or not isinstance(declared_sha, str) or len(declared_sha) != 64:
                raise BuildFailure(f"{sid} evidence proof lacks path/SHA")
            path = Path(path_value).expanduser().absolute()
            key = str(path)
            row_paths.append(key)
            if key not in seen:
                record = static_record(path, f"{sid} exact status proof")
                if record.get("sha256") != declared_sha.lower():
                    raise BuildFailure(f"{sid} proof SHA differs from status card: {path}")
                if isinstance(file.get("bytes"), int) and int(file["bytes"]) != int(record["stat_after"]["bytes"]):
                    raise BuildFailure(f"{sid} proof byte count differs from status card: {path}")
                seen.add(key)
            else:
                record = {"sha256": declared_sha.lower(), "stat_after": {"bytes": int(file.get("bytes", 0))}}
            output.append({"sentinel_id": sid, "path": key, "sha256": record["sha256"],
                           "bytes": record["stat_after"]["bytes"],
                           "claim_scope": item.get("claim_scope"),
                           "kind": item.get("kind"), "name": item.get("name")})
        if not row_paths:
            raise BuildFailure(f"{sid} proof binding is empty")
    return output

def _literal_python_record() -> dict[str, Any]:
    if not PYTHON.is_symlink() or not PYTHON.exists():
        raise BuildFailure(f"literal venv interpreter is unavailable: {PYTHON}")
    target = PYTHON.resolve()
    if not target.is_file():
        raise BuildFailure(f"literal venv target is unavailable: {target}")
    cfg = _record(PYVENV, "literal venv configuration")
    target_record = _record(target, "resolved venv interpreter")
    return {"literal_argv0": str(PYTHON), "resolved_target": str(target),
            "target_record": target_record, "pyvenv_record": cfg,
            "scope": "literal_venv_invocation_provenance"}

def _load(path: Path, label: str) -> dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise BuildFailure(f"{label} is not an object")
    return value

def _rows(report: dict[str,Any], key: str, label: str) -> dict[str,dict[str,Any]]:
    rows=report.get(key)
    if not isinstance(rows,list): raise BuildFailure(f"{label} lacks {key} list")
    out={}
    for row in rows:
        if isinstance(row,dict) and isinstance(row.get("sentinel_id"),str):
            out[row["sentinel_id"]]=row
    return out

def _motion_from_audit(row: dict[str,Any]) -> Path|None:
    resolution=row.get("motion_file_resolution") or {}
    for ref in resolution.get("references",[]) if isinstance(resolution,dict) else []:
        for candidate in ref.get("candidates",[]) if isinstance(ref,dict) else []:
            if isinstance(candidate,dict) and candidate.get("path") and Path(candidate["path"]).is_file():
                return Path(candidate["path"])
    return None

def _candidate_file(root: Path, label: str) -> Path:
    found=sorted((root/label).glob("*_Def.xml"))
    if len(found)!=1: raise BuildFailure(f"expected one {label} Def under {root}, found {found}")
    return found[0]

def _candidate_aux(root: Path, label: str, sid: str) -> Path|None:
    directory=root/label
    if sid=="F3-S1":
        vals=sorted(directory.glob("CaseSloshingAccData.csv"))
    else:
        vals=sorted(directory.rglob("*.dat"))
    return vals[0] if len(vals)==1 else None

def build(status_path: Path, audit_path: Path, bounds_path: Path, output_dir: Path) -> tuple[dict[str,Any],dict[str,Any]]:
    status_path,audit_path,bounds_path=[p.expanduser().absolute() for p in (status_path,audit_path,bounds_path)]
    status=_load(status_path,"status"); audit=_load(audit_path,"source audit"); bounds=_load(bounds_path,"geometry bounds")
    if status.get("schema")!="ds02.stage2.fourteen-source-status.v3": raise BuildFailure("status schema mismatch")
    if audit.get("schema")!="ds02.stage2.fourteen-source-control-audit.v5": raise BuildFailure("audit schema mismatch")
    if bounds.get("schema")!="ds02.stage2.continuum-geometry-bounds.v1": raise BuildFailure("bounds schema mismatch")
    audit_rows=_rows(audit,"sources","audit"); bound_rows=_rows(bounds,"sources","bounds")
    output_dir=output_dir.expanduser().absolute()
    output_dir.mkdir(parents=True,exist_ok=True)
    static=[]
    def static_record(path: Path,label: str) -> dict[str,Any]:
        r=_record(path,label)
        static.append(dict(r,label=label))
        return r
    status_rec=static_record(status_path,"14-sentinel status")
    audit_rec=static_record(audit_path,"14-sentinel source/control audit")
    bounds_rec=static_record(bounds_path,"continuum geometry bounds")
    if not DECLARED_INPUT_MANIFEST.is_file():
        raise BuildFailure(f"declared input manifest is missing: {DECLARED_INPUT_MANIFEST}")
    declared_manifest = _load(DECLARED_INPUT_MANIFEST, "declared spatial input manifest")
    declared_manifest_rec = static_record(DECLARED_INPUT_MANIFEST, "declared spatial input manifest")
    declared_sha = _declared_sha_map(declared_manifest)
    proof_bindings = _proof_bindings(status, static_record)
    tolerance_binding = {
        "authority": "fourteen-source-status-v3.frozen_gates",
        "source": status_rec,
        "frozen_gates": status.get("frozen_gates"),
        "numeric_values_declared_in_source": False,
        "numeric_tolerance_credit": "UNKNOWN_UNTIL_EXPLICIT_PREREGISTRATION",
    }
    deferred_sources: list[dict[str, Any]] = []
    cases=[]
    for sid in TARGETS:
        row=audit_rows.get(sid)
        if not isinstance(row,dict): raise BuildFailure(f"missing source audit row {sid}")
        xml_binding=row.get("source_xml")
        if not isinstance(xml_binding,dict) or not xml_binding.get("path"): raise BuildFailure(f"{sid} source XML binding missing")
        xml=Path(xml_binding["path"])
        source_xml=static_record(xml,f"{sid} generated source XML")
        source_def=xml.with_name(xml.stem+"_Def.xml")
        source_def_rec=static_record(source_def,f"{sid} source Def")
        control=row.get("source_solver_control") or {}
        receipt_binding=control.get("receipt")
        if not isinstance(receipt_binding,dict) or not receipt_binding.get("path"): raise BuildFailure(f"{sid} completed receipt missing")
        receipt=Path(receipt_binding["path"])
        receipt_rec=static_record(receipt,f"{sid} completed GenCase/solver receipt")
        # Prefer the exact motion path already identified by the source audit.
        motion=_motion_from_audit(row)
        if motion is None and sid=="F3-S1":
            candidate=xml.parent/"CaseSloshingAccData.csv"
            motion=candidate if candidate.is_file() else None
        if motion is not None and motion.stat().st_size > SMALL_CAP:
            motion_rec = _deferred_record(motion, f"{sid} source motion/forcing",
                                          declared_sha.get(str(motion.expanduser().absolute())))
            deferred_sources.append({"sentinel_id": sid, "grid_label": "source", **motion_rec})
        else:
            motion_rec=static_record(motion,f"{sid} source motion/forcing") if motion else None
        root=CANDIDATE_ROOTS[sid]
        grids=[]
        for label in GRID_LABELS:
            cand=_candidate_file(root,label)
            cand_rec=static_record(cand,f"{sid} {label} candidate Def")
            aux=_candidate_aux(root,label,sid)
            if aux is not None and aux.stat().st_size > SMALL_CAP:
                aux_rec = _deferred_record(aux, f"{sid} {label} candidate motion/forcing",
                                           declared_sha.get(str(aux.expanduser().absolute())))
                deferred_sources.append({"sentinel_id": sid, "grid_label": label, **aux_rec})
            else:
                aux_rec=static_record(aux,f"{sid} {label} candidate motion/forcing") if aux else None
            grids.append({"label":label,"candidate_def":cand_rec,"motion_or_forcing":aux_rec})
        cases.append({"sentinel_id":sid,"family_id":row.get("family_id"),"physical_case_id":row.get("physical_case_id"),
                      "source_xml":source_xml,"source_def":source_def_rec,"source_receipt":receipt_rec,
                      "motion_or_forcing":motion_rec,"grids":grids,
                      "source_audit_row": {"control_equivalence":row.get("control_equivalence"),
                          "motion_metadata_status":row.get("motion_metadata_status"),
                          "source_solver_control":row.get("source_solver_control")},
                      "geometry_bounds_row":bound_rows.get(sid)})
    worker=str(REF/"stage2_three_sentinel_owner_grid_source_audit_v3.py")
    worker_rec=static_record(Path(worker),"owner-grid source worker")
    python_record = _literal_python_record()
    static.append(python_record["target_record"] | {"label": "resolved venv interpreter"})
    static.append(python_record["pyvenv_record"] | {"label": "literal venv configuration"})
    # Deduplicate by path while retaining the strongest fully-read record.
    unique={}
    for item in static:
        prev=unique.get(item["path"])
        if prev is None or (not prev.get("read_by_builder") and item.get("read_by_builder")):
            unique[item["path"]]=item
    static=list(unique.values())
    manifest={"schema":SCHEMA,"status":"PREPARED_SOURCE_OWNER_GRID_AUDIT_V3","sentinel_ids":list(TARGETS),
              "source_inputs":{"status_report":status_rec,"source_control_audit":audit_rec,"geometry_bounds":bounds_rec,
                               "declared_spatial_input_manifest":declared_manifest_rec},
              "proof_bindings":proof_bindings,
              "tolerance_binding":tolerance_binding,
              "deferred_input_records":deferred_sources,
              "cases":cases,"static_sources":static,
              "frozen_gates":{"authority":tolerance_binding["authority"],
                  "source_sha256":status_rec["sha256"],"values":status.get("frozen_gates"),
                  "numeric_values_declared_in_source":False},
              "read_scope":{"bounded_xml_json_small_source_only":True,"production_payloads":False,
                  "forcing_csv_read_by_builder":False,"deferred_forcing_parent_hash":True,
                  "solver_launch":False,"gencase_launch":False}}
    manifest_path=output_dir/"owner-grid-source-manifest-v3.json"
    request_path=output_dir/"owner-grid-source-audit-v3-request.json"
    if manifest_path.exists() or request_path.exists(): raise BuildFailure("refuse overwrite immutable output")
    manifest_bytes=(json.dumps(manifest,indent=2,sort_keys=True,ensure_ascii=False)+"\n").encode()
    manifest_path.write_bytes(manifest_bytes)
    manifest_rec=_record(manifest_path,"generated owner-grid manifest")
    input_files=[item["path"] for item in static]+[str(manifest_path)]
    input_sha={item["path"]:item["sha256"] for item in static if item.get("sha256")}
    input_sha[str(manifest_path)]=manifest_rec["sha256"]
    request={"schema":REQUEST_SCHEMA,"status":"READY_FOR_PARENT_SOURCE_ONLY_OWNER_GRID_AUDIT",
             "request_variant":"source-only-owner-grid-v3","family_id":"DS-DATA-02",
             "sentinel_ids":list(TARGETS),"case_id":"F2_F3_F5_SOURCE_OWNER_GRID_AUDIT_V3",
             "attempt_id":"PARENT_ASSIGNED_AFTER_REVIEW","kind":"generic-cpu-audit","cpu_task_kind":"source_owner_grid_audit",
             "launch_allowed":False,"solver_launch":False,"gencase_launch":False,
             "command":[str(PYTHON),worker,"--run","--manifest",str(manifest_path),"--output",str(output_dir/"owner-grid-source-audit-v3.json")],
             "runtime_provenance":python_record,
             "input_files":input_files,"input_sha256":input_sha,"manifest_path":str(manifest_path),
             "deferred_input_files":[item["path"] for item in deferred_sources],
             "deferred_input_records":deferred_sources,
             "deferred_input_policy":{"parent_after_reservation_sha_stat":True,"builder_did_not_read":True,"source_replace_or_touch":"FAIL"},
             "proof_bindings":proof_bindings,"tolerance_binding":tolerance_binding,
             "output_path":str(output_dir/"owner-grid-source-audit-v3.json"),
             "resource_scope":{"cpu_threads":1,"max_wall_seconds":300,"memory_bytes":1073741824,
                 "scratch_bytes":8388608,"payload_read":False,"large_forcing_not_read":True},
             "scientific_qualification": {"QI":"UNKNOWN","QN":"UNKNOWN","QE":"UNKNOWN","scientific_credit":0}}
    request_bytes=(json.dumps(request,indent=2,sort_keys=True,ensure_ascii=False)+"\n").encode()
    request_path.write_bytes(request_bytes)
    return manifest,request

def _tiny_self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ds02-owner-builder-") as value:
        p=Path(value)
        source=p/"status.json"; source.write_text(json.dumps({"schema":"x"}))
        # The full builder is tested through the real source CLI; this small
        # guard only proves forbidden payload and immutable-record behavior.
        try: _record(p/"bad.bi4","payload")
        except BuildFailure: pass
        else: raise AssertionError("payload was accepted")
        assert _stat(source)["bytes"] > 0
    print("PASS_THREE_SENTINEL_OWNER_GRID_SOURCE_REQUEST_V3_SELFTEST")

def main(argv: list[str]|None=None)->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--status",type=Path,default=DEFAULT_STATUS)
    ap.add_argument("--audit",type=Path,default=DEFAULT_AUDIT)
    ap.add_argument("--bounds",type=Path,default=DEFAULT_BOUNDS)
    ap.add_argument("--output-dir",type=Path,required=False)
    args=ap.parse_args(argv)
    if args.self_test: _tiny_self_test(); return 0
    if args.output_dir is None: ap.error("--output-dir is required unless --self-test")
    try:
        manifest,request=build(args.status,args.audit,args.bounds,args.output_dir)
    except (BuildFailure,OSError,ValueError,KeyError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_SOURCE_REQUEST: {exc}",file=sys.stderr); return 2
    print(json.dumps({"status":request["status"],"manifest":request["manifest_path"],"request":str((args.output_dir/"owner-grid-source-audit-v3-request.json").absolute()),"static_sources":len(manifest["static_sources"]),"scientific_credit":0},sort_keys=True)); return 0

if __name__=="__main__":
    raise SystemExit(main())
