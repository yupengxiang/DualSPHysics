#!/usr/bin/env python3
"""Re-audit retained L1 evidence with finite-wall and runtime-domain semantics.

Q0 is a post-processing continuation of the previous L1 campaign.  It reads
the retained HDF5/solver evidence under ``campaigns/l1-qualification`` and
writes only compact, new evidence under ``campaigns/l1-resume/q0``.  No old
case, attempt, HDF5, or audit is modified.  The full per-case result is kept
under the ignored resume artifact directory so the compact report remains
reviewable while the operation stays reproducible.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Sequence

try:
    from scripts import l1_f1_qualification as l1
    from scripts import l1_w2_boundary_control as w2
    from scripts import r6_n2_campaign as r6
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import l1_f1_qualification as l1
    import l1_w2_boundary_control as w2
    import r6_n2_campaign as r6


LAB = Path(__file__).resolve().parents[1]
OLD_CAMPAIGN = LAB / "campaigns" / "l1-qualification"
RESUME_ROOT = LAB / "campaigns" / "l1-resume"
Q0_ROOT = RESUME_ROOT / "q0"
Q0_ARTIFACT_ROOT = RESUME_ROOT / "artifacts" / "q0-revised-audits"
REPORT = Q0_ROOT / "REVISED_AUDIT_SUMMARY.json"
ATTACHMENT = Path("/home/jade/.codex/attachments/10d77367-a21e-4886-b98f-c344c59c6d2d/L1R_404c565_2026-09-09.zip")
PLAN_BASELINE = "404c565c9b43e5470f1830e1e9b81843465c2c38"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(LAB.resolve()))
    except ValueError:
        return str(path.resolve())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def git_value(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=LAB, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _w1_records() -> list[dict[str, Any]]:
    return [dict(item) for item in l1.space_records(l1.TIME_PRIMARY_CFL)]


def _w2_record() -> dict[str, Any]:
    return dict(w2.build_record())


def source_records() -> list[dict[str, Any]]:
    """Return each unique retained HDF5 source used by the old space study."""
    rows = _w1_records()
    rows.append(_w2_record())
    return rows


def _source_paths(record: dict[str, Any]) -> tuple[Path, Path, Path | None]:
    case_id = str(record["case_id"])
    if case_id == w2.CASE_ID:
        h5_path = OLD_CAMPAIGN / "data" / "W2-A-boundary-mdbc" / f"{case_id}.h5"
        latest_path = OLD_CAMPAIGN / "runs" / "W2-A-boundary-mdbc" / case_id / "latest.json"
        old_audit = OLD_CAMPAIGN / "audits" / f"{case_id}.json"
    else:
        h5_path = OLD_CAMPAIGN / "data" / f"{case_id}.h5"
        latest_path = OLD_CAMPAIGN / "runs" / case_id / "latest.json"
        old_audit = OLD_CAMPAIGN / "audits" / f"{case_id}.json"
    attempt: Path | None = None
    if latest_path.is_file():
        try:
            payload = json.loads(latest_path.read_text(encoding="utf-8"))
            candidate = Path(payload["attempt_directory"])
            if candidate.is_dir():
                attempt = candidate
        except (KeyError, OSError, json.JSONDecodeError):
            attempt = None
    return h5_path, old_audit, attempt


def _old_compact(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "missing", "path": relpath(path)}
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return {"status": "invalid_json", "path": relpath(path), "error": repr(error)}
    penetration = old.get("penetration") or {}
    missing = old.get("missing_identity_classification") or {}
    return {
        "status": "available",
        "path": relpath(path),
        "sha256": sha256(path),
        "audit_status": old.get("audit_status"),
        "r6_full_time_audit_status": old.get("r6_full_time_audit_status"),
        "r6_hard_failures": old.get("r6_hard_failures", []),
        "issues": old.get("issues", []),
        "unknowns": old.get("unknowns", []),
        "initial_fluid_mass_kg": old.get("initial_fluid_mass_kg"),
        "final_valid_mass_kg": old.get("final_valid_mass_kg"),
        "final_valid_mass_fraction_of_initial": old.get("final_valid_mass_fraction_of_initial"),
        "initial_identities_missing_at_final": old.get("initial_identities_missing_at_final"),
        "excluded_particles_from_solver_log": old.get("excluded_particles_from_solver_log"),
        "penetration": {
            key: penetration.get(key)
            for key in (
                "frames_with_penetration", "first_penetration",
                "max_outside_closed_container_mass_kg", "max_obstacle_penetration_mass_kg",
            )
        },
        "missing_identity_status": missing.get("status"),
        "missing_identity_categories": missing.get("categories", {}),
    }


def _compact_revised(audit: dict[str, Any], *, artifact: Path) -> dict[str, Any]:
    penetration = audit.get("penetration") or {}
    missing = audit.get("missing_identity_classification") or {}
    return {
        "case_id": audit.get("case_id"),
        "background_id": audit.get("background_id"),
        "height_label": audit.get("height_label"),
        "resolution": audit.get("resolution"),
        "dp_m": audit.get("dp_m"),
        "audit_status": audit.get("audit_status"),
        "r6_full_time_audit_status": audit.get("r6_full_time_audit_status"),
        "r6_hard_failures": audit.get("r6_hard_failures", []),
        "issues": audit.get("issues", []),
        "unknowns": audit.get("unknowns", []),
        "initial_fluid_mass_kg": audit.get("initial_fluid_mass_kg"),
        "final_valid_mass_kg": audit.get("final_valid_mass_kg"),
        "final_valid_mass_fraction_of_initial": audit.get("final_valid_mass_fraction_of_initial"),
        "initial_identities_missing_at_final": audit.get("initial_identities_missing_at_final"),
        "excluded_particles_from_solver_log": audit.get("excluded_particles_from_solver_log"),
        "penetration": {
            key: penetration.get(key)
            for key in (
                "frames_with_penetration", "first_penetration",
                "max_outside_closed_container_mass_kg", "max_obstacle_penetration_mass_kg",
                "frames_with_runtime_domain_outside", "first_runtime_domain_outside",
                "frames_with_swept_crossing", "first_swept_crossing",
                "swept_crossing_count", "swept_crossing_particle_count",
                "swept_crossing_mass_kg", "swept_crossings_by_face",
                "swept_crossings_by_obstacle", "event_time_semantics",
                "geometry_semantics",
            )
        },
        "missing_identity_status": missing.get("status"),
        "missing_identity_categories": missing.get("categories", {}),
        "physical_wall_semantics": missing.get("physical_wall_semantics"),
        "runtime_domain": missing.get("runtime_domain"),
        "hdf5": audit.get("hdf5"),
        "hdf5_sha256": audit.get("hdf5_sha256"),
        "full_audit_artifact": relpath(artifact),
    }


def audit_one(record: dict[str, Any]) -> dict[str, Any]:
    case_id = str(record["case_id"])
    h5_path, old_audit_path, attempt = _source_paths(record)
    old = _old_compact(old_audit_path)
    common: dict[str, Any] = {
        "case_id": case_id,
        "old": old,
        "source": {
            "hdf5": relpath(h5_path),
            "hdf5_exists": h5_path.is_file(),
            "hdf5_sha256": sha256(h5_path) if h5_path.is_file() else None,
            "attempt_directory": relpath(attempt) if attempt is not None else None,
            "attempt_exists": attempt is not None,
        },
    }
    if not h5_path.is_file():
        return {**common, "revised": {"status": "blocked_missing_hdf5"}}
    started = time.perf_counter()
    try:
        audit = r6.full_time_audit(record, h5_path, attempt)
        artifact = Q0_ARTIFACT_ROOT / f"{case_id}.json"
        atomic_json(artifact, audit)
        revised = _compact_revised(audit, artifact=artifact)
        revised["elapsed_seconds"] = time.perf_counter() - started
        return {**common, "revised": revised}
    except Exception as error:  # Preserve one-case failures without losing the batch.
        return {
            **common,
            "revised": {
                "status": "audit_exception",
                "error": repr(error),
                "elapsed_seconds": time.perf_counter() - started,
            },
        }


def _select(case_ids: Sequence[str] | None) -> list[dict[str, Any]]:
    rows = source_records()
    if not case_ids:
        return rows
    wanted = set(case_ids)
    known = {str(row["case_id"]): row for row in rows}
    missing = sorted(wanted - set(known))
    if missing:
        raise ValueError(f"unknown Q0 case ids: {missing}")
    return [known[case_id] for case_id in case_ids]


def run(case_ids: Sequence[str] | None = None) -> dict[str, Any]:
    selected = _select(case_ids)
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    for record in selected:
        result = audit_one(record)
        results.append(result)
        print(json.dumps({
            "case_id": result["case_id"],
            "revised_status": result["revised"].get("r6_full_time_audit_status", result["revised"].get("status")),
            "elapsed_seconds": result["revised"].get("elapsed_seconds"),
        }, ensure_ascii=False), flush=True)

    by_height_resolution: dict[str, dict[str, Any]] = {}
    h10_by_resolution: dict[str, dict[str, Any]] = {}
    for result in results:
        revised = result["revised"]
        resolution = revised.get("resolution")
        height_label = revised.get("height_label")
        if resolution and height_label:
            key = f"{height_label}/{resolution}"
            # W2-A reuses the h11/fine discretisation.  Keep the W1 space
            # value as the resolution ledger entry and report W2 separately
            # in the case results rather than silently overwriting it.
            if key not in by_height_resolution:
                by_height_resolution[key] = {
                    "case_id": result["case_id"],
                    "initial_fluid_mass_kg": revised.get("initial_fluid_mass_kg"),
                    "height_label": height_label,
                    "resolution": resolution,
                }
            if height_label == "h10":
                h10_by_resolution[str(resolution)] = by_height_resolution[key]
    report = {
        "schema_version": "l1r.q0.revised-audit.v1",
        "generated_at_utc": utc_now(),
        "plan_baseline_commit": PLAN_BASELINE,
        "git_commit": git_value("rev-parse", "HEAD"),
        "git_branch": git_value("branch", "--show-current"),
        "attachment": {
            "path": str(ATTACHMENT),
            "exists": ATTACHMENT.is_file(),
            "sha256": sha256(ATTACHMENT) if ATTACHMENT.is_file() else None,
        },
        "scope": {
            "source_campaign": relpath(OLD_CAMPAIGN),
            "old_evidence_modified": False,
            "new_output_root": relpath(Q0_ROOT),
            "selected_case_ids": [str(record["case_id"]) for record in selected],
            "semantics": "finite closed physical faces; open top excluded; explicit runtime domain separate; saved-frame chord intervals are diagnostic locators",
        },
        "initial_mass_by_height_resolution": by_height_resolution,
        "h10_initial_mass_by_resolution": h10_by_resolution,
        "elapsed_seconds": time.perf_counter() - started,
        "results": results,
    }
    atomic_json(REPORT, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", action="append", dest="case_ids", help="audit one retained case; repeat to select a subset")
    args = parser.parse_args(argv)
    run(args.case_ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
