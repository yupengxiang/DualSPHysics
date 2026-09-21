#!/usr/bin/env python3
"""Audit the distributed-slot CPU/native failure without rerunning it."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

# Direct script execution needs the lab root on the import path.
LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.r4_f6_mdbc_runtime_zero_normal_audit import read_binary_vtk


BASE = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-v1"
PREFLIGHT = BASE / "preflight-v1/preflight.json"
BOUND = BASE / "preflight-v1/generated/F2_SLOT_TRANSFER_q0p50000000_dp0p007500000000_anchor_Bound.vtk"
XML = BASE / "preflight-v1/generated/F2_SLOT_TRANSFER_q0p50000000_dp0p007500000000_anchor.xml"
DEFAULT_OUTPUT = LAB_ROOT / "campaigns/core-v1/evidence/f2-distributed-slot-preflight-negative-evidence-v1.json"
DEFAULT_REPORT = LAB_ROOT / "reports/F2-DISTRIBUTED-SLOT-PREFLIGHT-NEGATIVE-2026-09-21.zh-CN.md"
SCHEMA = "core.f2.distributed_slot_transfer.cpu_native_negative_evidence.v1"
ZERO_TOLERANCE = 1.0e-12


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def summarize(points: np.ndarray, mk: np.ndarray, normal: np.ndarray, normal_size: np.ndarray) -> dict[str, Any]:
    points = np.asarray(points, dtype=float)
    mk = np.asarray(mk)
    normal = np.asarray(normal, dtype=float)
    normal_size = np.asarray(normal_size, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or normal.shape != points.shape or normal_size.shape != (len(points),):
        raise ValueError("malformed boundary arrays")
    zero = np.linalg.norm(normal, axis=1) <= ZERO_TOLERANCE
    rows = []
    for value in sorted(set(int(x) for x in mk.tolist())):
        selected = mk == value
        rows.append({
            "mk": value,
            "particle_count": int(selected.sum()),
            "zero_boundnor_count": int(zero[selected].sum()),
            "zero_normal_size_count": int((normal_size[selected] <= ZERO_TOLERANCE).sum()),
            "zero_fraction": float(zero[selected].mean()) if selected.any() else 0.0,
            "normal_norm_min_m": float(np.linalg.norm(normal[selected], axis=1).min()) if selected.any() else None,
            "normal_norm_max_m": float(np.linalg.norm(normal[selected], axis=1).max()) if selected.any() else None,
            "zero_bbox_m": {
                "min": points[selected & zero].min(axis=0).tolist() if np.any(selected & zero) else None,
                "max": points[selected & zero].max(axis=0).tolist() if np.any(selected & zero) else None,
            },
        })
    return {
        "boundary_particles": int(len(points)),
        "zero_boundnor_count": int(zero.sum()),
        "zero_normal_size_count": int((normal_size <= ZERO_TOLERANCE).sum()),
        "mk_partitions": rows,
        "arrays_finite": bool(np.isfinite(points).all() and np.isfinite(normal).all() and np.isfinite(normal_size).all()),
    }


def audit(output: Path = DEFAULT_OUTPUT, report: Path = DEFAULT_REPORT) -> dict[str, Any]:
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if preflight.get("schema") != "core.f2.distributed_slot_transfer.cpu_native_preflight.v1":
        raise ValueError("unexpected preflight schema")
    if preflight.get("preflight_pass") is not False or preflight.get("status") != "cpu_native_preflight_failed_hard_audit":
        raise ValueError("distributed-slot preflight is not a hard negative")
    controls = preflight.get("execution_controls", {})
    for key in ("solver_invoked", "gpu_invoked", "job_created", "matrix_submission"):
        if controls.get(key) not in (False, 0):
            raise ValueError(f"negative evidence opened protected action: {key}")
    vtk = read_binary_vtk(BOUND)
    fields = vtk["point_data"]
    summary = summarize(vtk["points"], fields["Mk"], fields["Normal"], fields["NormalSize"])
    observed = preflight["native_initial"]
    if summary["boundary_particles"] != observed["boundary_particles_decoded"]:
        raise ValueError("Bound.vtk particle count disagrees with preflight")
    if summary["zero_boundnor_count"] != observed["zero_boundnor_count"]:
        raise ValueError("Bound.vtk zero-normal count disagrees with preflight")
    evidence = {
        "schema": SCHEMA,
        "status": "completed_negative_result",
        "family": "F2",
        "scope_id": "F2_distributed_submerged_slot_transfer_x_v1",
        "case_id": preflight["case_id"],
        "qualification_claim": "none",
        "T1_numerical": False,
        "matrix_credit": 0,
        "failure_class": "cpu_native_zero_boundnor_and_normal_size",
        "preflight": {
            "status": preflight["status"],
            "preflight_pass": False,
            "generated_counts": preflight["generated_counts"],
            "native_initial": preflight["native_initial"],
            "mass_contract": preflight["mass_contract"],
        },
        "partition": summary,
        "interpretation": {
            "zero_normal_mk17_outer_count": next(row["zero_boundnor_count"] for row in summary["mk_partitions"] if row["mk"] == 17),
            "zero_normal_mk18_gate_count": next(row["zero_boundnor_count"] for row in summary["mk_partitions"] if row["mk"] == 18),
            "hypothesis_for_review_only": "mirror GeometryForNormals layer offsets to the fresh mainlist shell layers 0,-1,-2 for both outer tank and four gate-frame boxes",
            "hypothesis_status": "unexecuted; requires a new root-review-only proposal and new output stem",
            "same_input_retry": False,
            "threshold_relaxation": False,
        },
        "execution_controls": {
            "gencase_invoked_in_source_attempt": True,
            "native_decoder_invoked_in_source_attempt": True,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
            "qualification_credit": 0,
        },
        "hash_bindings": {
            "preflight": ref(PREFLIGHT, "fresh distributed-slot CPU/native preflight"),
            "bound_vtk": ref(BOUND, "read-only boundary normal field"),
            "generated_xml": ref(XML, "read-only GenCase particle identity XML"),
            "audit_implementation": ref(Path(__file__), "read-only partition audit"),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    lines = [
        "# F2 distributed-slot CPU/native preflight negative evidence",
        "",
        "Status: **hard negative; zero T1 credit; solver route closed for this input stem**.",
        "",
        f"The fresh GenCase/native preflight generated {summary['boundary_particles']:,} boundary and {preflight['generated_counts']['fluid_particles']:,} fluid particles. Native source mass error was {preflight['mass_contract']['relative_error']:.6%} and passed the mass gate, but {summary['zero_boundnor_count']:,} boundary normals and {summary['zero_normal_size_count']:,} NormalSize values were zero.",
        "",
        "The failure is partitioned by the generated Mk field: the outer tank (Mk=17) and the distributed gate frame (Mk=18) both contain zero-normal particles. This audit proposes only a falsifiable layer-offset hypothesis; it does not modify the failed Definition or rerun it.",
        "",
        "No solver, GPU, queue, ledger, registry, matrix, or qualification credit was used.",
        "",
        "## Hash closure",
        "",
    ]
    for key, item in evidence["hash_bindings"].items():
        lines.append(f"- `{key}`: `{item['sha256']}` ({item['bytes']} bytes)")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    result = audit(args.output, args.report)
    print(json.dumps({"status": result["status"], "zero_boundnor_count": result["partition"]["zero_boundnor_count"], "matrix_credit": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
