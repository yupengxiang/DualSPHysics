#!/usr/bin/env python3
"""Materialize the current 41-record, explicit fourteen-sentinel index.

The v4 status registry is only the source list.  This additive builder gives
each record one declared sentinel and one declared research dimension, checks
the exact small proof SHA/size, and writes current stat metadata.  Dimension
membership is the literal table below; it is never inferred from a filename,
status word, or claim text.  The four additional ROOT207/217/227/252 proofs
are bound explicitly so the index reflects the current source evidence rather
than the older 37-record status list.

Only small JSON metadata/proof files are read.  QI/QN/QE and scientific credit
remain UNKNOWN/zero; this is an evidence index, not a qualification result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

STATUS_PATH = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_fourteen_evidence_status_v4.json"
)
CATALOG_SCHEMA = "ds02.stage2.fourteen-reference-evidence-dimension-catalog.v2"
STATUS_SCHEMA = "ds02.stage2.fourteen-sentinel-evidence-status.v4"
SENTINELS = tuple(f"F{family}-S{sentinel}" for family in range(1, 8) for sentinel in (1, 2))
DIMENSIONS = (
    "spatial_three_grid", "time_step", "output_sampling", "initial_support",
    "control_initial", "native_fields", "external_anchor",
    "integral_vs_output_separated",
)
SMALL_CAP = 10 * 1024 * 1024
UNKNOWN = "UNKNOWN"

# (sentinel_id, dimension, actual, observed, note).  The index is explicit by
# source-list position; changing the source list requires changing this table.
SOURCE_ASSIGNMENTS: tuple[tuple[str, str, bool, bool, str], ...] = (
    ("F1-S1", "spatial_three_grid", True, True, "cross-grid COM diagnostic"),
    ("F1-S1", "time_step", True, True, "same-CFL native selected frames"),
    ("F1-S1", "output_sampling", True, True, "half-CFL saved-time diagnostic"),
    ("F1-S1", "native_fields", True, True, "selected native observer fields"),
    ("F1-S1", "integral_vs_output_separated", True, True, "aggregate arithmetic only"),
    ("F1-S2", "spatial_three_grid", True, True, "coarse/fine source diagnostics"),
    ("F1-S2", "output_sampling", True, True, "full-window output diagnostics"),
    ("F1-S2", "time_step", True, True, "three-interval source diagnostic"),
    ("F2-S1", "output_sampling", True, True, "coarse full-CFD output"),
    ("F2-S1", "time_step", True, True, "fine native timing"),
    ("F2-S1", "initial_support", True, True, "continuum/source mass mismatch"),
    ("F2-S2", "control_initial", False, False, "source/control ladder plan; not a run"),
    ("F3-S1", "external_anchor", True, True, "family anchor labels"),
    ("F3-S1", "time_step", True, True, "full-window phase recovery"),
    ("F3-S2", "spatial_three_grid", False, False, "matched three-grid plan"),
    ("F3-S2", "initial_support", True, True, "dp015 support audit"),
    ("F3-S2", "native_fields", True, True, "dp003 source/mass support"),
    ("F4-S1", "time_step", True, True, "same-CFL saved-time evidence"),
    ("F4-S1", "output_sampling", True, True, "half-CFL saved-time evidence"),
    ("F4-S1", "spatial_three_grid", True, True, "fine full-window diagnostic"),
    ("F4-S1", "integral_vs_output_separated", True, True, "observer comparison"),
    ("F4-S1", "native_fields", True, True, "lossless full-window fields"),
    ("F4-S2", "output_sampling", False, False, "saved-time/CFL pair binding plan"),
    ("F5-S1", "initial_support", True, True, "clip-plane mass hard-fail/support"),
    ("F5-S1", "native_fields", True, True, "dp010 initial support"),
    ("F5-S1", "spatial_three_grid", True, True, "dp005 initial support"),
    ("F5-S1", "output_sampling", True, True, "storage/output projection"),
    ("F5-S2", "control_initial", False, False, "effective-condition source plan"),
    ("F6-S1", "initial_support", True, True, "shared F6 source-owner authority proof, indexed to S1"),
    ("F6-S1", "native_fields", True, True, "shared F6 rigid-cloud diagnostic, indexed to S1"),
    ("F6-S1", "integral_vs_output_separated", True, True, "shared F6 rigid-observation diagnostic, indexed to S1"),
    ("F7-S1", "external_anchor", True, True, "family anchor labels"),
    ("F7-S1", "initial_support", True, True, "mass-fit diagnostic"),
    ("F7-S2", "native_fields", True, True, "full native observer"),
    ("F7-S2", "time_step", True, True, "half-CFL seventeen-frame observer"),
    ("F7-S2", "output_sampling", True, True, "joined calibration"),
    ("F7-S2", "integral_vs_output_separated", True, True, "same/half field comparison"),
)

EXTRA_PROOFS: tuple[dict[str, Any], ...] = (
    {
        "evidence_id": "E38_ROOT207_F1_NATIVE",
        "sentinel_id": "F1-S2",
        "dimension": "native_fields",
        "actual": True,
        "observed": True,
        "path": "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
                "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/"
                "F1_NATIVE_SELECTED_OBSERVER_V5_ACTUAL_ROOT_VERIFICATION_207.json",
        "sha256": "c2016d5a36922230eafc57c49baadaeff3a2bc920bb953b5fef215eb9fda30ab",
        "note": "ROOT207 actual native selected fields; axis/Q remain unknown",
        "covered_sentinels": ["F1-S1", "F1-S2"],
    },
    {
        "evidence_id": "E39_ROOT217_F1_WRITER",
        "sentinel_id": "F1-S1",
        "dimension": "external_anchor",
        "actual": True,
        "observed": True,
        "path": "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
                "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/"
                "OFFICIAL_WRITER_CALIBRATION_V4_ACTUAL_ROOT_VERIFICATION_217.json",
        "sha256": "7df9b02c339e3b3eb8bae8f108c16d5db0fd2b6cb3f03d192c4edc827ae1bdf0",
        "note": "ROOT217 manufactured writer/decoder contract only",
    },
    {
        "evidence_id": "E40_ROOT227_F1_OWNER",
        "sentinel_id": "F1-S2",
        "dimension": "initial_support",
        "actual": True,
        "observed": True,
        "path": "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
                "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/"
                "F1_S2_CONTINUOUS_OWNER_AUDIT_V2_ACTUAL_ROOT_VERIFICATION_227.json",
        "sha256": "d0edf2364db892cbe16670992c22328354b6a3dcd19d6857c8d528dc17781e1a",
        "note": "ROOT227 owner audit; fee closure does not grant Q",
    },
    {
        "evidence_id": "E41_ROOT252_F6_OWNER",
        "sentinel_id": "F6-S2",
        "dimension": "initial_support",
        "actual": True,
        "observed": True,
        "path": "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/"
                "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/"
                "F6_CONTINUOUS_OWNER_GEOMETRY_AUDIT_V1_ACTUAL_ROOT_VERIFICATION_252.json",
        "sha256": "016978a604208d8581788223fc0af3c99adf7316cec7f6b2bea762513d3a5c6b",
        "note": "ROOT252 continuous owner geometry/support audit covers F6-S1 and F6-S2",
        "covered_sentinels": ["F6-S1", "F6-S2"],
    },
)


class CatalogFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _read_small(path: Path, label: str) -> tuple[dict[str, Any], str, dict[str, int]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise CatalogFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > SMALL_CAP:
        raise CatalogFailure(f"{label} exceeds 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise CatalogFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CatalogFailure(f"{label} must be a JSON object")
    return value, hashlib.sha256(raw).hexdigest(), after


def _record(
    *, evidence_id: str, sentinel: str, dimension: str, actual: bool,
    observed: bool, path: str, expected_sha: str | None, note: str,
    origin: str, covered_sentinels: list[str] | None = None,
) -> dict[str, Any]:
    if sentinel not in SENTINELS or dimension not in DIMENSIONS:
        raise CatalogFailure(f"invalid explicit assignment: {evidence_id}")
    value, sha, stat = _read_small(Path(path), evidence_id)
    if expected_sha and sha != expected_sha.lower():
        raise CatalogFailure(f"{evidence_id} SHA differs from declared proof SHA")
    result: dict[str, Any] = {
        "evidence_id": evidence_id,
        "sentinel_id": sentinel,
        "dimension": dimension,
        "actual": bool(actual),
        "observed": bool(observed),
        "scope": "small_proof" if actual and observed else "source_plan",
        "status": "ACTUAL_DIAGNOSTIC_SMALL_PROOF" if actual and observed else "SOURCE_PLAN_NOT_EXECUTED",
        "note": note,
        "origin": origin,
        "source_registry_schema": STATUS_SCHEMA,
        "path": str(Path(path).expanduser().absolute()),
        "sha256": sha,
        "stat": stat,
        "read_mode": "small_read",
        "payload_read_by_builder": False,
        "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0},
    }
    if covered_sentinels:
        result["covered_sentinels"] = covered_sentinels
    return result


def build(status_path: Path, output_path: Path) -> dict[str, Any]:
    status, status_sha, status_stat = _read_small(status_path, "v4 fourteen-sentinel status registry")
    if status.get("schema") != STATUS_SCHEMA:
        raise CatalogFailure("status registry schema mismatch")
    source_inputs = status.get("source_inputs")
    if not isinstance(source_inputs, list) or len(source_inputs) != len(SOURCE_ASSIGNMENTS):
        raise CatalogFailure("status registry source_inputs does not contain the expected 37 records")
    records: list[dict[str, Any]] = []
    for index, (sentinel, dimension, actual, observed, note) in enumerate(SOURCE_ASSIGNMENTS):
        item = source_inputs[index]
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise CatalogFailure(f"source_inputs[{index}] lacks a path")
        records.append(_record(
            evidence_id=f"E{index + 1:02d}_{sentinel.replace('-', '_')}_{dimension}",
            sentinel=sentinel, dimension=dimension, actual=actual, observed=observed,
            path=item["path"], expected_sha=item.get("sha256"), note=note,
            origin="status_v4.source_inputs",
        ))
    for extra in EXTRA_PROOFS:
        records.append(_record(
            evidence_id=str(extra["evidence_id"]), sentinel=str(extra["sentinel_id"]),
            dimension=str(extra["dimension"]), actual=bool(extra["actual"]),
            observed=bool(extra["observed"]), path=str(extra["path"]),
            expected_sha=str(extra["sha256"]), note=str(extra["note"]),
            origin="current_root_proof_registry_addendum",
            covered_sentinels=list(extra.get("covered_sentinels", [])) or None,
        ))
    if len(records) != 41:
        raise CatalogFailure(f"catalog has {len(records)} records, expected 41")
    pairs = [(str(row["sentinel_id"]), str(row["dimension"])) for row in records]
    if len(set(pairs)) != len(pairs):
        raise CatalogFailure("catalog contains duplicate sentinel/dimension pairs")
    catalog = {
        "schema": CATALOG_SCHEMA,
        "status": "CURRENT_EXPLICIT_41_RECORD_FOURTEEN_SENTINEL_INDEX_NO_SCIENTIFIC_Q",
        "record_count": len(records),
        "dimension_vocabulary": list(DIMENSIONS),
        "sentinel_vocabulary": list(SENTINELS),
        "records": records,
        "source_registry": {
            "path": str(status_path.expanduser().absolute()),
            "sha256": status_sha,
            "stat": status_stat,
            "read_mode": "small_read",
        },
        "read_scope": {
            "status_registry_and_proof_json_only": True,
            "metadata_cap_bytes": SMALL_CAP,
            "production_native_vtk_bi4_h5_read": False,
            "solver_or_gencase_launch": False,
            "dimension_inferred_from_status_text": False,
        },
        "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0},
    }
    output_path = output_path.expanduser().absolute()
    if output_path.exists() or output_path.is_symlink():
        raise CatalogFailure(f"refusing overwrite: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(catalog, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return catalog


def _self_test() -> None:
    # The real build below is the authoritative check.  This test only checks
    # the literal assignment cardinality and duplicate guard without opening
    # production evidence.
    assert len(SOURCE_ASSIGNMENTS) == 37
    assert len(EXTRA_PROOFS) == 4
    assert len(SOURCE_ASSIGNMENTS) + len(EXTRA_PROOFS) == 41
    pairs = [(row[0], row[1]) for row in SOURCE_ASSIGNMENTS]
    pairs.extend((str(row["sentinel_id"]), str(row["dimension"])) for row in EXTRA_PROOFS)
    assert len(pairs) == len(set(pairs))
    assert all(sentinel in SENTINELS and dimension in DIMENSIONS for sentinel, dimension in pairs)
    print("PASS_FOURTEEN_EVIDENCE_DIMENSION_CATALOG_V2_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--status", type=Path, default=STATUS_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            _self_test()
        except Exception as exc:
            print(f"FAILED_FOURTEEN_EVIDENCE_DIMENSION_CATALOG_V2_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.output is None:
        parser.error("--build requires --output")
    try:
        value = build(args.status, args.output)
    except (CatalogFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOURTEEN_EVIDENCE_DIMENSION_CATALOG_V2: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": value["status"], "record_count": value["record_count"],
                      "output": str(args.output.expanduser().absolute()), "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
