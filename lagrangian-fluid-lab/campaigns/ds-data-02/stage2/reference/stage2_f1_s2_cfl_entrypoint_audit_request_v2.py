#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the bounded source/receipt/XML CFL-entrypoint audit request."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER = HERE / "stage2_f1_s2_cfl_entrypoint_audit_v2.py"
CONTRACT = HERE / "stage2_f1_s2_cfl_entrypoint_audit_contract_v2.json"
SCHEMA = "ds02.request.v1"
INPUT_MANIFEST_SCHEMA = "ds02.stage2.f1-s2.cfl-entrypoint-manifest.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.cfl-entrypoint-manifest.v2"
MAX_JSON = 8 * 1024 * 1024
MAX_XML = 2 * 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024


class BuildFailure(RuntimeError):
    pass


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    return path.absolute()


def _stat(path: Path) -> dict[str, int]:
    s = path.stat(); return {"dev": int(s.st_dev), "ino": int(s.st_ino), "bytes": int(s.st_size), "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _record(path: Path, label: str, limit: int) -> dict[str, Any]:
    path = _regular(path, label); before = _stat(path)
    if before["bytes"] > limit: raise BuildFailure(f"{label} exceeds bounded limit")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
    after = _stat(path)
    if before != after: raise BuildFailure(f"{label} changed while being read")
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": after["bytes"], "stat": after, "stable_read": True, "label": label, "content_scope": "bounded_metadata_or_official_source"}


def _path(value: Any, label: str) -> Path:
    if isinstance(value, str): return Path(value)
    if isinstance(value, dict) and isinstance(value.get("path"), str): return Path(value["path"])
    raise BuildFailure(f"{label} missing path")


def _python_binding() -> dict[str, Any]:
    literal = PYTHON.expanduser()
    if not literal.is_symlink(): raise BuildFailure("literal venv Python must remain a symlink")
    resolved = _regular(literal.resolve(), "resolved venv Python")
    cfg = literal.parent.parent / "pyvenv.cfg"
    return {"literal_argv0": str(literal), "literal_argv0_required": True, "resolved": _record(resolved, "resolved venv Python", 8 * 1024 * 1024), "pyvenv_cfg": _record(cfg, "pyvenv.cfg", MAX_SOURCE)}


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink(): raise BuildFailure(f"refusing overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"); os.replace(temporary, path)
    finally: temporary.unlink(missing_ok=True)


def _canonical(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in value.items() if k != "sha256"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    record = _record(path, label, MAX_JSON)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not JSON") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not a JSON object")
    return value, record


def _same_path(left: Any, right: str) -> bool:
    return isinstance(left, str) and Path(left).expanduser().absolute() == Path(right).expanduser().absolute()


def _lineage(source: dict[str, Any], source_record: dict[str, Any], receipt: dict[str, Any], label: str) -> dict[str, Any]:
    embedded = receipt.get("request")
    if not isinstance(embedded, dict):
        raise BuildFailure(f"{label} receipt has no embedded request")
    binding = embedded.get("root_canonical_binding")
    if isinstance(binding, dict):
        if not _same_path(binding.get("source_request"), source_record["path"]):
            raise BuildFailure(f"{label} root source request path mismatch")
        if str(binding.get("source_sha256") or "").lower() != source_record["sha256"]:
            raise BuildFailure(f"{label} root source request SHA mismatch")
        kind = "source_request_to_embedded_root_canonical_binding"
    elif _same_path(embedded.get("path"), source_record["path"]) and str(embedded.get("sha256") or "").lower() == source_record["sha256"]:
        kind = "direct_source_request"
    else:
        raise BuildFailure(f"{label} receipt request is not source-bound")
    return {"status": "PASS_SOURCE_REQUEST_LINEAGE_JOIN", "join_kind": kind,
            "source_request": source_record,
            "source_request_semantics": {key: source.get(key) for key in ("schema", "case_id", "physical_case_id", "attempt_id")},
            "embedded_receipt_request": {key: embedded[key] for key in ("schema", "case_id", "physical_case_id", "attempt_id") if key in embedded},
            "root_canonical_binding_verified": isinstance(binding, dict),
            "direct_source_to_receipt_request_sha": kind == "direct_source_request"}


def build(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = _regular(args.manifest, "F1 CFL manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != INPUT_MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_F1_CFL_ENTRYPOINT_AUDIT": raise BuildFailure("source manifest schema/status mismatch")
    entries = manifest.get("entries"); sources = manifest.get("official_sources")
    if not isinstance(entries, list) or not entries or not isinstance(sources, list) or not sources: raise BuildFailure("manifest entries/sources missing")
    records: dict[str, dict[str, Any]] = {}
    manifest_record = _record(manifest_path, "F1 CFL manifest", MAX_JSON); records[manifest_record["path"]] = manifest_record
    for i, source in enumerate(sources):
        record = _record(_path(source, f"official source {i}"), f"official source {i}", MAX_SOURCE); records[record["path"]] = record
    lineage_by_label: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict): raise BuildFailure(f"entry {index} is not an object")
        request_value, request_record = _read_json(_path(entry.get("request"), f"entry {index} request"), f"entry {index} source request")
        receipt_value, receipt_record = _read_json(_path(entry.get("receipt"), f"entry {index} receipt"), f"entry {index} terminal receipt")
        lineage_by_label[str(entry.get("label", index))] = _lineage(request_value, request_record, receipt_value, str(entry.get("label", index)))
        records[request_record["path"]] = request_record
        records[receipt_record["path"]] = receipt_record
        for key, limit in (("xml", MAX_XML),):
            path = _path(entry.get(key), f"entry {index} {key}")
            if path.suffix.lower() in {".bi4", ".h5", ".vtk", ".part", ".csv"}: raise BuildFailure(f"payload path in entry {index} {key}")
            record = _record(path, f"entry {index} {key}", limit); records[record["path"]] = record
    output_manifest = _regular(args.manifest_v2_output, "F1 CFL v2 manifest output") if args.manifest_v2_output.exists() else args.manifest_v2_output.expanduser().absolute()
    v2_entries = []
    for entry in entries:
        label = str(entry.get("label", "entry"))
        v2_entry = dict(entry)
        v2_entry["request_lineage"] = lineage_by_label[label]
        v2_entry["request"] = {"path": lineage_by_label[label]["source_request"]["path"], "sha256": lineage_by_label[label]["source_request"]["sha256"]}
        v2_entry["receipt"] = {"path": records[_path(entry["receipt"], f"{label} receipt").expanduser().absolute().as_posix()]["path"], "sha256": records[_path(entry["receipt"], f"{label} receipt").expanduser().absolute().as_posix()]["sha256"]}
        v2_entries.append(v2_entry)
    v2_manifest = {"schema": MANIFEST_SCHEMA, "status": "PREPARED_NOT_RUN_F1_CFL_ENTRYPOINT_AUDIT_V2",
                   "source_manifest": records[manifest_record["path"]], "official_sources": sources,
                   "entries": v2_entries, "lineage_policy": "source request must join receipt embedded request directly or through exact root_canonical_binding source path/SHA",
                   "source_authority_policy": "actual XML execution authority includes JCaseCtes::ReadXmlRun and receipt execution constants; ReadXmlDef alone is insufficient",
                   "interpolation": False, "neighbor_grid_truth": False,
                   "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    _write_once(output_manifest, v2_manifest)
    manifest_v2_record = _record(output_manifest, "F1 CFL v2 manifest", MAX_JSON)
    records[manifest_v2_record["path"]] = manifest_v2_record
    worker_record = _record(WORKER, "F1 CFL worker", MAX_SOURCE); records[worker_record["path"]] = worker_record
    contract_record = _record(CONTRACT, "F1 CFL contract", MAX_JSON); records[contract_record["path"]] = contract_record
    py = _python_binding(); records[py["resolved"]["path"]] = py["resolved"]; records[py["pyvenv_cfg"]["path"]] = py["pyvenv_cfg"]
    files = sorted(records); hashes = {path: records[path]["sha256"] for path in files}
    root_label = getattr(args, "root_label", "ROOT254")
    if not root_label.startswith("ROOT") or not root_label[4:].replace("_", "").isalnum():
        raise BuildFailure(f"invalid source request root label: {root_label}")
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": "ds02.stage2.f1-s2.cfl-entrypoint-audit-request.v2",
        "status": f"READY_FOR_PARENT_V8_F1_CFL_ENTRYPOINT_AUDIT_{root_label}_V2",
        "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F1", "sentinel_id": "F1-S2",
        "case_id": args.case_id, "attempt_id": args.attempt_id, "launch_commit": args.launch_commit,
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"),
        "command": [str(PYTHON), str(WORKER), "--manifest", "{attempt_root}/inputs/f1_s2_cfl_entrypoint_manifest_v2.json", "--output", "{attempt_root}/control/f1_s2_cfl_entrypoint_audit_v2.json"],
        "input_files": files, "input_hashes": hashes, "input_sha256": hashes, "input_records": records, "deferred_input_files": [],
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 600, "max_memory_bytes": 1024 * 1024 * 1024,
        "estimated_storage_bytes": 8 * 1024 * 1024, "estimated_peak_memory_bytes": 256 * 1024 * 1024,
        "estimated_input_read_bytes": sum(int(record["bytes"]) for record in records.values()), "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "solver_launch": False, "gencase_launch": False,
        "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "runparts_read": False, "raw_directory_scan": False,
        "output_root": "{attempt_root}", "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/control/f1_s2_cfl_entrypoint_audit_v2.json"},
        "source_binding": {"receipt_launch_argv_authority": True, "xml_cflnumber_authority_when_no_-cfl": True, "execution_xml_authority": "JCaseCtes::ReadXmlRun plus actual receipt execution constants", "request_lineage_exact_source_sha": True, "labels_not_evidence": True, "source_request_namespace": root_label, "half_cfl_overlay_status": "SOURCE_ONLY_PREPARED_NOT_RUN", "interpolation": False, "neighbor_grid_truth": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
        "resource_guard": {"runner": "parent-v8-audit", "native_payload": "forbidden", "solver_launch": "forbidden", "large_report": "forbidden"},
    }
    request["sha256"] = _canonical(request); _write_once(args.output_request, request); return request


def _self_test() -> None:
    assert _canonical({"x": 1}) == _canonical({"x": 1})
    try: _path({"path": "bad.bi4"}, "payload")
    except BuildFailure: pass
    with tempfile.TemporaryDirectory(prefix="f1-cfl-v2-lineage-") as directory:
        root = Path(directory)
        source = root / "source.json"; source.write_text(json.dumps({"schema": "source", "case_id": "S"}), encoding="utf-8")
        source_record = _record(source, "source", MAX_JSON)
        receipt = {"request": {"root_canonical_binding": {"source_request": str(source), "source_sha256": source_record["sha256"]}}}
        assert _lineage(json.loads(json.dumps({"schema": "source", "case_id": "S"})), source_record, receipt, "fixture")["root_canonical_binding_verified"]
        bad = {"request": {"root_canonical_binding": {"source_request": str(source), "source_sha256": "0" * 64}}}
        try: _lineage({}, source_record, bad, "bad")
        except BuildFailure: pass
        else: raise AssertionError("wrong root source SHA accepted")
    print("PASS_F1_CFL_ENTRYPOINT_REQUEST_V2_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--manifest", type=Path); parser.add_argument("--manifest-v2-output", type=Path); parser.add_argument("--output-request", type=Path); parser.add_argument("--case-id", default="F1_S2_CFL_ENTRYPOINT_AUDIT_ROOT254_V2"); parser.add_argument("--attempt-id", default="f1-s2-cfl-entrypoint-audit-v2-root-254-001"); parser.add_argument("--launch-commit", default="SOURCE_ONLY_ROOT254_V2"); parser.add_argument("--root-label", default="ROOT254"); parser.add_argument("--self-test", action="store_true"); args = parser.parse_args()
    if args.self_test: _self_test(); return 0
    if args.manifest is None or args.manifest_v2_output is None or args.output_request is None: parser.error("--manifest, --manifest-v2-output and --output-request are required unless --self-test")
    try: request = build(args)
    except Exception as exc: print(f"FAILED_F1_CFL_ENTRYPOINT_REQUEST: {exc}"); return 2
    print(json.dumps({"status": request["status"], "request": str(args.output_request.absolute()), "sha256": request["sha256"]}, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
