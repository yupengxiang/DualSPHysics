#!/usr/bin/env python3
"""Build the launch-disabled, source-only F1-S2 owner audit manifest/request.

This builder hashes only the small owner/Def/XML/receipt/code files.  ROOT207
and ROOT217 proof files are deferred: the guarded worker hashes and parses
those after reservation, then checks the proof->report->case identity edges.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_f1_s2_continuous_owner_audit_v2.py"
CONTRACT = HERE / "stage2_f1_s2_continuous_owner_audit_contract_v2.json"
PROJECT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
OWNER = HERE.parent.parent / "handoff_20261003/root_stage1_f1_four_physical_head_endpoints_native_032/F1_STAGE1_DUAL_H340_DP020/owner.json"
SOURCE_DIR = PROJECT / "families/F1/F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/prepared"
SOURCE_DEF = SOURCE_DIR / "F1_STAGE1_DUAL_H340_DP020_Def.xml"
SOURCE_XML = SOURCE_DIR / "F1_STAGE1_DUAL_H340_DP020.xml"
SOURCE_RECEIPT = SOURCE_DIR.parent / "execution-receipt.json"
COARSE_XML = PROJECT / "families/F1/F1_S2_SPATIAL_COARSE_DP0p022500/f1-s2-spatial-coarse-dp0p022500-v5-primary-001/generated.xml"
FINE_XML = PROJECT / "families/F1/F1_S2_SPATIAL_INTERVAL_DP0p017000/f1-s2-spatial-interval-dp0p017000-v2-primary-001/generated.xml"
ROOT207_PROOF = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_NATIVE_SELECTED_OBSERVER_V5_ACTUAL_ROOT_VERIFICATION_207.json")
ROOT217_PROOF = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/OFFICIAL_WRITER_CALIBRATION_V4_ACTUAL_ROOT_VERIFICATION_217.json")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"
SCHEMA = "ds02.stage2.f1-s2.continuous-owner-audit-manifest.v2"
REQUEST_SCHEMA = "ds02.stage2.generic-cpu-audit-request.v2"
ROOT207_SHA = "c2016d5a36922230eafc57c49baadaeff3a2bc920bb953b5fef215eb9fda30ab"
ROOT217_SHA = "7df9b02c339e3b3eb8bae8f108c16d5db0fd2b6cb3f03d192c4edc827ae1bdf0"


class BuildError(RuntimeError):
    pass


def sha256(path: Path, max_bytes: int = 16 * 1024 * 1024) -> str:
    if path.is_symlink() or not path.is_file():
        raise BuildError(f"source is not a regular file: {path}")
    if path.stat().st_size > max_bytes:
        raise BuildError(f"source exceeds bounded builder read: {path}")
    before = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino, before.st_dev) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino, after.st_dev):
        raise BuildError(f"source changed while hashing: {path}")
    return digest


def record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    st = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": st.st_size,
        "sha256": sha256(path),
        "stat_fields": {"dev": st.st_dev, "ino": st.st_ino, "mtime_ns": st.st_mtime_ns, "ctime_ns": st.st_ctime_ns},
        "content_scope": "small source or metadata; no production native payload",
    }


def literal_python_record() -> dict[str, Any]:
    path = PYTHON.expanduser()
    if not path.is_file():
        raise BuildError(f"literal venv interpreter is missing: {path}")
    target = path.resolve()
    return {
        "path": str(path),
        "argv0_literal": True,
        "resolved_target": str(target),
        "resolved_target_sha256": sha256(target),
        "pyvenv_cfg": record(PYVENV, "literal venv pyvenv.cfg"),
        "target_is_within_venv": str(target).startswith(str(path.parent.parent.resolve())),
    }


def build_manifest(path: Path) -> dict[str, Any]:
    sources = [
        record(WORKER, "audit worker"),
        record(CONTRACT, "frozen owner audit contract"),
        record(OWNER, "continuous owner authority"),
        record(SOURCE_DEF, "canonical source Def"),
        record(SOURCE_RECEIPT, "canonical GenCase receipt"),
        record(SOURCE_XML, "medium generated XML / owner source XML"),
        record(COARSE_XML, "coarse generated XML"),
        record(FINE_XML, "fine generated XML"),
    ]
    source_by = {item["label"]: item for item in sources}
    return {
        "schema": SCHEMA,
        "status": "PREPARED_NOT_RUN_SOURCE_ONLY",
        "sentinel_id": "F1-S2",
        "family_id": "F1",
        "case_id": "F1_S2_CONTINUOUS_OWNER_SOURCE_AUDIT_ROOT222",
        "contract_path": str(CONTRACT.resolve()),
        "contract_sha256": source_by["frozen owner audit contract"]["sha256"],
        "owner": {"path": str(OWNER.resolve()), "sha256": source_by["continuous owner authority"]["sha256"]},
        "source_def": {"path": str(SOURCE_DEF.resolve()), "sha256": source_by["canonical source Def"]["sha256"]},
        "receipt": {"path": str(SOURCE_RECEIPT.resolve()), "sha256": source_by["canonical GenCase receipt"]["sha256"]},
        "grids": [
            {"label": "coarse", "path": str(COARSE_XML.resolve()), "sha256": source_by["coarse generated XML"]["sha256"]},
            {"label": "medium", "path": str(SOURCE_XML.resolve()), "sha256": source_by["medium generated XML / owner source XML"]["sha256"]},
            {"label": "fine", "path": str(FINE_XML.resolve()), "sha256": source_by["fine generated XML"]["sha256"]},
        ],
        "proofs": {
            "root207": {"path": str(ROOT207_PROOF), "sha256": ROOT207_SHA, "content_scope": "deferred guarded proof; worker must join child report, not wrapper-only report"},
            "root217": {"path": str(ROOT217_PROOF), "sha256": ROOT217_SHA, "content_scope": "deferred guarded manufactured calibration proof/report"},
        },
        "static_source_records": sources,
        "literal_python": literal_python_record(),
        "read_scope": {
            "small_json_xml_code_only": True,
            "maximum_per_file_bytes": 16 * 1024 * 1024,
            "production_bi4_h5_vtk_read": False,
            "solver_launch": False,
            "ledger_mutation": False,
        },
    }


def request_from_manifest(manifest: dict[str, Any], manifest_path: Path, request_path: Path) -> dict[str, Any]:
    input_records = list(manifest["static_source_records"])
    input_records.append({"path": str(manifest_path.resolve()), "label": "audit manifest", "sha256": sha256(manifest_path)})
    return {
        "schema": REQUEST_SCHEMA,
        "status": "PREPARED_NOT_RUN_SOURCE_ONLY",
        "kind": "audit",
        "cpu_task_kind": "audit",
        "request_id": "f1-s2-continuous-owner-audit-v2-root222-001",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "case_id": manifest["case_id"],
        "attempt_id": "f1-s2-continuous-owner-audit-v2-root222-001",
        "command": [str(PYTHON), str(WORKER), "--manifest", str(manifest_path.resolve()), "--output", "{attempt_root}/owner-audit.json"],
        "literal_venv_invocation": manifest["literal_python"],
        "manifest": {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path)},
        "input_files": [item["path"] for item in input_records],
        "input_sha256": {item["path"]: item["sha256"] for item in input_records},
        "proof_inputs_deferred": {
            "root207_proof": manifest["proofs"]["root207"],
            "root217_proof": manifest["proofs"]["root217"],
        },
        "resources": {
            "gpu": False,
            "cpu_cores": 1,
            "max_wall_seconds": 300,
            "memory_max_bytes": 1024 * 1024 * 1024,
            "scratch_max_bytes": 64 * 1024 * 1024,
            "log_max_bytes": 1024 * 1024,
        },
        "scientific_scope": {
            "owner_mass_kg": 340.0,
            "native_support": "UNKNOWN_UNTIL_ONE_FRAME_PER_GRID_GUARDED_POSITION_AUDIT",
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
            "no_neighbor_grid_truth": True,
            "no_mass_rescale": True,
        },
        "source_scope": "small owner/Def/generated XML/receipt/proof/report only; no BI4/H5/VTK/native array reads",
        "source_records": input_records,
    }


def write_immutable(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def self_test() -> None:
    assert WORKER.is_file() and CONTRACT.is_file()
    assert ROOT207_SHA == "c2016d5a36922230eafc57c49baadaeff3a2bc920bb953b5fef215eb9fda30ab"
    assert ROOT217_SHA == "7df9b02c339e3b3eb8bae8f108c16d5db0fd2b6cb3f03d192c4edc827ae1bdf0"
    print("PASS_F1_S2_CONTINUOUS_OWNER_AUDIT_REQUEST_V2_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            return 0
        if args.manifest is None or args.request is None:
            parser.error("--manifest and --request are required unless --self-test is used")
        manifest = build_manifest(args.manifest)
        write_immutable(args.manifest, manifest)
        request = request_from_manifest(manifest, args.manifest, args.request)
        write_immutable(args.request, request)
        print(f"PASS_PREPARED_F1_S2_OWNER_AUDIT {args.manifest} {args.request}")
        return 0
    except (BuildError, OSError, ValueError, KeyError) as exc:
        print(f"FAIL_F1_S2_OWNER_AUDIT_REQUEST: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
