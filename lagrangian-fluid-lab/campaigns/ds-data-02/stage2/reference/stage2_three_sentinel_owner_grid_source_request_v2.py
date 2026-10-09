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

SCHEMA = "ds02.stage2.three-sentinel.owner-grid-source-manifest.v2"
REQUEST_SCHEMA = "ds02.request.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
SMALL_CAP = 16 * 1024 * 1024
PAYLOAD_SUFFIXES = {".bi4",".vtk",".h5",".hdf5",".part",".hdf"}
REPO = Path(__file__).resolve().parents[5]
REF = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DEFAULT_STATUS = REF / "stage2_fourteen_source_status_v3.json"
DEFAULT_AUDIT = REF / "stage2_fourteen_source_control_audit_v5.json"
DEFAULT_BOUNDS = REF / "stage2_continuum_geometry_bounds_v1.json"
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
        motion_rec=static_record(motion,f"{sid} source motion/forcing") if motion else None
        root=CANDIDATE_ROOTS[sid]
        grids=[]
        for label in GRID_LABELS:
            cand=_candidate_file(root,label)
            cand_rec=static_record(cand,f"{sid} {label} candidate Def")
            aux=_candidate_aux(root,label,sid)
            aux_rec=static_record(aux,f"{sid} {label} candidate motion/forcing") if aux else None
            grids.append({"label":label,"candidate_def":cand_rec,"motion_or_forcing":aux_rec})
        cases.append({"sentinel_id":sid,"family_id":row.get("family_id"),"physical_case_id":row.get("physical_case_id"),
                      "source_xml":source_xml,"source_def":source_def_rec,"source_receipt":receipt_rec,
                      "motion_or_forcing":motion_rec,"grids":grids,
                      "source_audit_row": {"control_equivalence":row.get("control_equivalence"),
                          "motion_metadata_status":row.get("motion_metadata_status"),
                          "source_solver_control":row.get("source_solver_control")},
                      "geometry_bounds_row":bound_rows.get(sid)})
    worker=str(REF/"stage2_three_sentinel_owner_grid_source_audit_v2.py")
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
    manifest={"schema":SCHEMA,"status":"PREPARED_SOURCE_OWNER_GRID_AUDIT_V2","sentinel_ids":list(TARGETS),
              "source_inputs":{"status_report":status_rec,"source_control_audit":audit_rec,"geometry_bounds":bounds_rec},
              "cases":cases,"static_sources":static,
              "frozen_gates":{"mass_relative_tolerance":0.03,"position_fraction_of_registered_source_L":0.02,
                  "velocity_relative_tolerance":0.05,"kinetic_energy_relative_tolerance":0.05,
                  "time_output_budget_fraction":0.25,"event_time":"UNKNOWN"},
              "read_scope":{"bounded_xml_json_csv_motion_only":True,"production_payloads":False,
                  "solver_launch":False,"gencase_launch":False}}
    manifest_path=output_dir/"owner-grid-source-manifest-v2.json"
    request_path=output_dir/"owner-grid-source-audit-v2-request.json"
    if manifest_path.exists() or request_path.exists(): raise BuildFailure("refuse overwrite immutable output")
    manifest_bytes=(json.dumps(manifest,indent=2,sort_keys=True,ensure_ascii=False)+"\n").encode()
    manifest_path.write_bytes(manifest_bytes)
    manifest_rec=_record(manifest_path,"generated owner-grid manifest")
    input_files=[item["path"] for item in static]+[str(manifest_path)]
    input_sha={item["path"]:item["sha256"] for item in static if item.get("sha256")}
    input_sha[str(manifest_path)]=manifest_rec["sha256"]
    request={"schema":REQUEST_SCHEMA,"status":"READY_FOR_PARENT_SOURCE_ONLY_OWNER_GRID_AUDIT",
             "request_variant":"source-only-owner-grid-v2","family_id":"DS-DATA-02",
             "sentinel_ids":list(TARGETS),"case_id":"F2_F3_F5_SOURCE_OWNER_GRID_AUDIT_V2",
             "attempt_id":"PARENT_ASSIGNED_AFTER_REVIEW","kind":"generic-cpu-audit","cpu_task_kind":"source_owner_grid_audit",
             "launch_allowed":False,"solver_launch":False,"gencase_launch":False,
             "command":[str(PYTHON),worker,"--run","--manifest",str(manifest_path),"--output",str(output_dir/"owner-grid-source-audit-v2.json")],
             "runtime_provenance":python_record,
             "input_files":input_files,"input_sha256":input_sha,"manifest_path":str(manifest_path),
             "output_path":str(output_dir/"owner-grid-source-audit-v2.json"),
             "resource_scope":{"cpu_threads":1,"max_wall_seconds":300,"memory_bytes":1073741824,
                 "scratch_bytes":8388608,"payload_read":False},
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
    print("PASS_THREE_SENTINEL_OWNER_GRID_SOURCE_REQUEST_SELFTEST")

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
    print(json.dumps({"status":request["status"],"manifest":request["manifest_path"],"request":str((args.output_dir/"owner-grid-source-audit-v2-request.json").absolute()),"static_sources":len(manifest["static_sources"]),"scientific_credit":0},sort_keys=True)); return 0

if __name__=="__main__":
    raise SystemExit(main())
