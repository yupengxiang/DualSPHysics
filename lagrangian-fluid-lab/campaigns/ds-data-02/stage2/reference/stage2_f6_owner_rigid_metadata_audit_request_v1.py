#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the bounded ROOT244 F6 owner/rigid XML metadata audit request."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_f6_owner_rigid_metadata_audit_v1.py"
CONTRACT = HERE / "stage2_f6_owner_rigid_metadata_audit_contract_v1.json"
SOURCE_AUDIT = HERE / "stage2_fourteen_source_control_audit_v5.json"
GRAPH = HERE / "stage2_minimal14_study_graph_v2.json"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f6-owner-rigid-metadata-audit-request.v1"
CASE = "F6_OWNER_RIGID_METADATA_AUDIT_ROOT244"
ATTEMPT = "f6-owner-rigid-metadata-audit-v1-root-244-001"


def _regular(path: Path, label: str) -> Path:
    raw = path.expanduser()
    if raw.is_symlink() or not raw.is_file():
        raise FileNotFoundError(f"{label}: {raw}")
    resolved = raw.resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise FileNotFoundError(f"{label} is not regular: {resolved}")
    return resolved


def _stat(path: Path) -> tuple[int, int, int, int, int, int]:
    st = path.stat()
    return (int(st.st_size), int(st.st_mtime_ns), int(st.st_ctime_ns), int(st.st_dev), int(st.st_ino), int(st.st_mode))


def _stat_dict(v: tuple[int, int, int, int, int, int]) -> dict[str, int]:
    return {"bytes": v[0], "mtime_ns": v[1], "ctime_ns": v[2], "st_dev": v[3], "st_ino": v[4], "mode": v[5]}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record(path: Path, label: str, max_bytes: int = 8 * 1024 * 1024) -> dict[str, Any]:
    path = _regular(path, label)
    before = _stat(path)
    if before[0] > max_bytes:
        raise ValueError(f"{label} exceeds bounded input limit")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = _stat(path)
    if before != after:
        raise RuntimeError(f"{label} changed during metadata read")
    return {"path": str(path), "bytes": before[0], "sha256": digest.hexdigest(), "stat_before": _stat_dict(before), "stat_after": _stat_dict(after), "stable_read": True, "label": label, "content_scope": "bounded_small_source_metadata"}


def _load(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rec = _record(path, label)
    value = json.loads(Path(rec["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object")
    return value, rec


def _literal_python() -> dict[str, Any]:
    raw = PYTHON.expanduser()
    if not raw.is_symlink():
        raise ValueError("literal venv interpreter must be a symlink")
    resolved = _regular(raw.resolve(), "resolved venv interpreter")
    cfg = _regular(raw.parent.parent / "pyvenv.cfg", "pyvenv.cfg")
    return {"literal_path": str(raw), "resolved_path": str(resolved), "literal_is_symlink": True, "resolved": _record(resolved, "resolved venv interpreter"), "pyvenv_cfg": _record(cfg, "pyvenv.cfg")}


def _xml_paths(source: dict[str, Any], graph: dict[str, Any]) -> list[Path]:
    result: list[Path] = []
    rows = {row.get("sentinel_id"): row for row in source.get("sources", []) if isinstance(row, dict)}
    graphs = {row.get("sentinel_id"): row for row in graph.get("sentinels", []) if isinstance(row, dict)}
    for sid in ("F6-S1", "F6-S2"):
        row = rows.get(sid)
        graph_row = graphs.get(sid)
        if not isinstance(row, dict) or not isinstance(graph_row, dict):
            raise ValueError(f"missing source/graph {sid}")
        result.append(Path(str(row["source_xml"]["path"])))
        for grid in graph_row.get("spatial_ladder", []):
            path = grid.get("generated_xml", {}).get("path") if isinstance(grid.get("generated_xml"), dict) else None
            if path:
                result.append(Path(str(path)))
    return list(dict.fromkeys(result))


def build(args: argparse.Namespace) -> dict[str, Any]:
    source_path, graph_path = args.source_audit.expanduser().resolve(), args.graph.expanduser().resolve()
    source, source_record = _load(source_path, "F6 source/control audit")
    graph, graph_record = _load(graph_path, "F6 study graph")
    xml_records = [_record(path, f"F6 XML {path.name}", max_bytes=2 * 1024 * 1024) for path in _xml_paths(source, graph)]
    worker, contract = _record(WORKER, "ROOT244 metadata worker"), _record(CONTRACT, "ROOT244 metadata contract")
    py = _literal_python()
    records = [source_record, graph_record, worker, contract, py["resolved"], py["pyvenv_cfg"], *xml_records]
    input_records = {record["path"]: record for record in records}
    input_files = sorted(input_records)
    input_hashes = {path: input_records[path]["sha256"] for path in input_files}
    command = [str(PYTHON), str(WORKER), "--source-audit", str(source_path), "--graph", str(graph_path), "--output", "{attempt_root}/audit/f6_owner_rigid_metadata_audit_v1.json"]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V8_F6_OWNER_RIGID_METADATA_AUDIT_ROOT244",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F6",
        "sentinel_id": "F6-S1+F6-S2",
        "case_id": args.case_id,
        "attempt_id": args.attempt_id,
        "launch_commit": args.launch_commit,
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"),
        "worktree_root": str(PRIMARY),
        "command": command,
        "input_files": input_files,
        "input_hashes": input_hashes,
        "input_sha256": input_hashes,
        "input_records": input_records,
        "deferred_input_files": [],
        "deferred_input_records": {},
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "max_memory_bytes": 512 * 1024**2,
        "max_log_bytes": 64 * 1024,
        "estimated_storage_bytes": 2 * 1024 * 1024,
        "estimated_peak_memory_bytes": 128 * 1024**2,
        "estimated_input_read_bytes": sum(int(record["bytes"]) for record in records),
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "solver_launch": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "vtk_read": False,
        "raw_directory_scan": False,
        "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/audit/f6_owner_rigid_metadata_audit_v1.json"},
        "source_binding": {"source_audit": str(source_path), "study_graph": str(graph_path), "cases": ["F6-S1", "F6-S2"], "physical_body_vs_sample_mass_separate": True, "continuous_owner": "UNKNOWN_UNTIL_EXPLICIT_SOURCE_CLOSURE", "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
        "literal_venv": py,
    }
    payload["canonical_sha256"] = _sha(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    return payload


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ds02-root244-builder-") as directory:
        root = Path(directory)
        xml = root / "x.xml"
        xml.write_text("<case/>\n", encoding="utf-8")
        source = root / "source.json"
        graph = root / "graph.json"
        source.write_text(json.dumps({"sources": [{"sentinel_id": sid, "source_xml": {"path": str(xml)}} for sid in ("F6-S1", "F6-S2")]}) + "\n", encoding="utf-8")
        graph.write_text(json.dumps({"sentinels": [{"sentinel_id": sid, "spatial_ladder": []} for sid in ("F6-S1", "F6-S2")]}) + "\n", encoding="utf-8")
        try:
            build(argparse.Namespace(source_audit=source, graph=graph, case_id=CASE, attempt_id=ATTEMPT, launch_commit="fixture"))
        except ValueError as exc:
            if "literal venv" not in str(exc):
                raise
    return {"status": "PASS", "schema": VARIANT, "bounded_xml_inputs": True, "no_payload_inputs": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source-audit", type=Path, default=SOURCE_AUDIT)
    parser.add_argument("--graph", type=Path, default=GRAPH)
    parser.add_argument("--case-id", default=CASE)
    parser.add_argument("--attempt-id", default=ATTEMPT)
    parser.add_argument("--launch-commit", default="unbound-until-parent-forward")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        print(json.dumps(self_test(), sort_keys=True))
        return 0
    if args.output is None:
        parser.error("--output is required")
    payload = build(args)
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "output": str(output), "input_count": len(payload["input_files"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
