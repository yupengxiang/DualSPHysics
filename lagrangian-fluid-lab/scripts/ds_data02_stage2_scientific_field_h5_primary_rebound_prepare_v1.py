#!/usr/bin/env python3
"""Rebuild the additive V3 H5 source package against one primary checkout.

The frozen V3 package was prepared from an isolated worktree.  This wrapper
does not edit or rewrite those files.  After the V3 worker and bounded V4
verifier are integrated into the chosen primary checkout, it invokes the
versioned V3 builder once with every path explicitly rebound to that checkout
and writes a fresh 43-group package plus a seven-proof pilot index.

Only small JSON/source metadata is read here.  The H5 paths remain deferred
and no H5, BI4, native payload, solver, or guard is opened or started.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any


SCRIPT = Path(__file__).resolve()
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
MASTER_SHA256 = "f396bcaa87e34cb40ac312fd6f00c93d9dacd2ec7f2c056622e5c5ac420fb76d"
MAX_JSON_BYTES = 10 * 1024 * 1024
PILOTS = (
    ("F1", "TYPED_LIFECYCLE_BATCH_F1_ACTUAL_ROOT_VERIFICATION_286.json", "F1_DUAL_HEAD_340_VX_150_FRESH090_V1"),
    ("F2", "TYPED_LIFECYCLE_BATCH_F2_ACTUAL_ROOT_VERIFICATION_289.json", "F2_STAGE1_FIRST8_OFFSET_OPEN_RIM_RX050_RY014_FILL080"),
    ("F3", "TYPED_LIFECYCLE_BATCH_F3_ACTUAL_ROOT_VERIFICATION_294.json", "F3_TWOAXIS_PITCH1000_AY0540_STAGE1_FIRST24_NEW"),
    ("F4", "TYPED_LIFECYCLE_BATCH_F4_ACTUAL_ROOT_VERIFICATION_280.json", "F4_DROP_gap0p24000_xoffm0p08000_yoff0p04000_uz0p60000"),
    ("F5", "TYPED_LIFECYCLE_BATCH_F5_ACTUAL_ROOT_VERIFICATION_302.json", "F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T100"),
    ("F6", "TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_281.json", "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S130_DP025"),
    ("F7", "TYPED_LIFECYCLE_BATCH_F7_ACTUAL_ROOT_VERIFICATION_304.json", "F7_OBSTACLE_QUINTIC_B08_A036P5"),
)


class ReboundError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Any, label: str, *, max_bytes: int = MAX_JSON_BYTES) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not value:
        raise ReboundError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ReboundError(f"{label} is missing: {path}")
    if path.stat().st_size > max_bytes:
        raise ReboundError(f"{label} exceeds bounded metadata size: {path}")
    return path


def static_ref(path: Path, role: str) -> dict[str, Any]:
    path = require_file(path, role)
    value = path.stat()
    return {
        "role": role, "path": str(path), "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev), "st_ino": int(value.st_ino),
        "sha256": sha256_file(path), "content_read_by_preparer": True,
    }


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = require_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReboundError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ReboundError(f"{label} is not a JSON object")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise ReboundError(f"refusing to overwrite immutable rebound output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > MAX_JSON_BYTES:
            raise ReboundError(f"rebound output exceeds bounded JSON size: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_base(primary_root: Path):
    base_path = primary_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_scientific_field_h5_batch_request_prepare_v3.py"
    base_path = require_file(base_path, "primary V3 batch builder")
    spec = importlib.util.spec_from_file_location("ds02_h5_batch_builder_v3_primary", base_path)
    if spec is None or spec.loader is None:
        raise ReboundError("cannot import primary V3 batch builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SCRIPT = base_path
    module.PRIMARY_ROOT = primary_root
    module.LAB_ROOT = primary_root
    module.STAGE2_ROOT = primary_root / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
    return module, base_path


def recursive_case_rows(value: Any, case_id: str) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        found = [value] if value.get("physical_case_id") == case_id else []
        for child in value.values():
            found.extend(recursive_case_rows(child, case_id))
        return found
    if isinstance(value, list):
        found: list[dict[str, Any]] = []
        for child in value:
            found.extend(recursive_case_rows(child, case_id))
        return found
    return []


def build_pilot_index(primary_root: Path, output_dir: Path, current_path: Path, root307_proof: Path) -> dict[str, Any]:
    current = read_json(current_path, "primary CURRENT336")
    if current.get("schema") != "ds02.stage2.current336.v1" or not isinstance(current.get("cases"), list) or len(current["cases"]) != 336:
        raise ReboundError("primary CURRENT is not the exact 336-case catalog")
    current_map = {row.get("physical_case_id"): row for row in current["cases"] if isinstance(row, dict)}
    if len(current_map) != 336:
        raise ReboundError("primary CURRENT case IDs are not unique")
    root307 = read_json(root307_proof, "ROOT307 actual 335 proof")
    coverage = root307.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("actual_saved_mask_cases") != 335 or coverage.get("current_cases") != 336 or coverage.get("historical_alias_unresolved") != 1:
        raise ReboundError("ROOT307 proof does not bind 335 exact cases plus one alias")
    pilots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for family, proof_name, case_id in PILOTS:
        if case_id in seen:
            raise ReboundError(f"duplicate pilot case: {case_id}")
        seen.add(case_id)
        row = current_map.get(case_id)
        if not isinstance(row, dict) or row.get("family_id") != family:
            raise ReboundError(f"pilot {case_id} is not the expected CURRENT family case")
        proof_path = primary_root / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints" / proof_name
        proof = read_json(proof_path, f"{family} pilot terminal proof")
        if not isinstance(proof.get("status"), str) or not proof["status"].startswith("VERIFIED_ACTUAL_"):
            raise ReboundError(f"{family} pilot proof is not terminal actual")
        proof_rows = recursive_case_rows(proof.get("case_verifications"), case_id)
        if len(proof_rows) != 1:
            raise ReboundError(f"{family} pilot proof lacks one exact case row")
        pilots.append({
            "family_id": family, "physical_case_id": case_id,
            "terminal_proof": static_ref(proof_path, f"{family} pilot terminal proof"),
            "current_row_index": row.get("current_index"),
            "status": "SOURCE_BOUND_PILOT_METADATA_ONLY",
            "production_payload_opened": False, "scientific_credit": 0,
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        })
    value = {
        "schema": "ds02.stage2.scientific-field-h5-primary-rebound.v1",
        "status": "SOURCE_PREPARED_PRIMARY_REBOUND_NOT_RUN",
        "primary_root": str(primary_root),
        "current": {**static_ref(current_path, "primary CURRENT336"), "cases": 336, "sha256": CURRENT_SHA256, "alias_excluded": True},
        "root307_actual_335_proof": {**static_ref(root307_proof, "ROOT307 actual 335 proof"), "actual_saved_mask_cases": 335, "historical_alias_unresolved": 1},
        "pilot_count": len(pilots), "pilots": pilots,
        "batch_package": {"path": str(output_dir), "status": "SOURCE_PREPARED_BATCH_GROUPS_NOT_RUN", "groups_expected": 43, "cases_expected": 335},
        "read_policy": {"metadata_only": True, "trajectory_h5_opened": False, "trajectory_h5_hashed": False, "bi4_opened": False, "solver_started": False, "guard_started": False},
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "units": "DECLARED_ONLY_UNVERIFIED", "material_and_mk": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }
    path = output_dir / "scientific-field-h5-primary-rebound-v3-pilot-index.json"
    atomic_json(path, value)
    return {"pilot_index": str(path), "pilot_index_sha256": sha256_file(path), "pilot_count": len(pilots)}


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    primary_root = Path(args.primary_root).expanduser().resolve()
    if not primary_root.is_dir():
        raise ReboundError(f"primary root is missing: {primary_root}")
    base, base_path = load_base(primary_root)
    stage2 = primary_root / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
    current = Path(args.current).expanduser().resolve() if args.current else stage2 / "CURRENT336.json"
    output = Path(args.output_dir).expanduser().resolve()
    namespace = argparse.Namespace(
        source_manifest=Path(args.source_manifest).expanduser().resolve() if args.source_manifest else stage2 / "requests/scientific-field-h5-335-batch-source-prepared-001/scientific-field-h5-335-batch-manifest.json",
        current=current,
        plan=Path(args.plan).expanduser().resolve() if args.plan else stage2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json",
        registry=Path(args.registry).expanduser().resolve() if args.registry else stage2 / "requests/typed-lifecycle-evidence-registry-v4-after-root307-001.json",
        worker=Path(args.worker).expanduser().resolve() if args.worker else primary_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_scientific_field_h5_audit_v3.py",
        v2_worker=Path(args.v2_worker).expanduser().resolve() if args.v2_worker else primary_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_scientific_field_h5_audit_v2.py",
        verifier=Path(args.verifier).expanduser().resolve() if args.verifier else primary_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_verify_scientific_field_h5_audit_v4.py",
        runtime=Path(args.runtime).expanduser().resolve() if args.runtime else primary_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
        dispatch=Path(args.dispatch).expanduser().resolve() if args.dispatch else primary_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
        strict=Path(args.strict).expanduser().resolve() if args.strict else primary_root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
        python=Path(args.python).expanduser() if args.python else Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"),
        config=Path(args.config).expanduser().resolve() if args.config else Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"),
        chunk=args.chunk, max_wall_seconds=args.max_wall_seconds, max_memory_bytes=args.max_memory_bytes,
        limit_groups=args.limit_groups, output_dir=output, report=None,
    )
    # Make all default/module-owned paths point to the selected primary.  The
    # base builder does the strict CURRENT/master/alias/group checks.
    base.PRIMARY_ROOT = primary_root
    base.LAB_ROOT = primary_root
    base.STAGE2_ROOT = stage2
    base.SCRIPT = base_path
    result = base.prepare(namespace)
    root307 = Path(args.root307_proof).expanduser().resolve() if args.root307_proof else stage2 / "checkpoints/ROOT307_ACTUAL_LIFECYCLE_METADATA_INDEPENDENT_CLOSURE_V1.json"
    pilot = build_pilot_index(primary_root, output, current, root307)
    result.update(pilot)
    result.update({"primary_root": str(primary_root), "worker": str(namespace.worker), "verifier": str(namespace.verifier), "current_sha256": CURRENT_SHA256, "groups": 43, "cases": 335, "source_read_policy": {"h5_opened": False, "h5_hashed": False, "launch": False}})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-root", type=Path, default=SCRIPT.parents[2])
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--current", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--root307-proof", type=Path)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--v2-worker", type=Path)
    parser.add_argument("--verifier", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--dispatch", type=Path)
    parser.add_argument("--strict", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--chunk", type=int, default=65536)
    parser.add_argument("--max-wall-seconds", type=int, default=3600)
    parser.add_argument("--max-memory-bytes", type=int, default=4 * 1024**3)
    parser.add_argument("--limit-groups", type=int, default=0)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = prepare(args)
    except (ReboundError, OSError, ValueError) as exc:
        print(f"scientific-field-h5-primary-rebound-prepare: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
