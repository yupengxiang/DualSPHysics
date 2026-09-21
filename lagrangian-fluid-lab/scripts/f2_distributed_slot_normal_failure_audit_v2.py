#!/usr/bin/env python3
"""Close the v2 distributed-slot normal repair after its hard preflight failure."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.f2_distributed_slot_failure_audit_v1 import summarize  # noqa: E402
from scripts.r4_f6_mdbc_runtime_zero_normal_audit import read_binary_vtk  # noqa: E402


BASE = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-v1/normal-repair-v2"
PREFLIGHT = BASE / "preflight-v2/preflight.json"
BOUND = BASE / "preflight-v2/generated/F2_SLOT_TRANSFER_q0p50000000_dp0p007500000000_anchor_v2_Bound.vtk"
XML = BASE / "preflight-v2/generated/F2_SLOT_TRANSFER_q0p50000000_dp0p007500000000_anchor_v2.xml"
DEFAULT_OUTPUT = LAB_ROOT / "campaigns/core-v1/evidence/f2-distributed-slot-normal-repair-v2-negative-evidence.json"
DEFAULT_REPORT = LAB_ROOT / "reports/F2-DISTRIBUTED-SLOT-NORMAL-REPAIR-V2-NEGATIVE-2026-09-21.zh-CN.md"
SCHEMA = "core.f2.distributed_slot_transfer.normal_repair_negative_evidence.v2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def audit(output: Path = DEFAULT_OUTPUT, report: Path = DEFAULT_REPORT) -> dict[str, Any]:
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if preflight.get("schema") != "core.f2.distributed_slot_transfer.normal_repair_cpu_native_preflight.v2" or preflight.get("preflight_pass") is not False:
        raise ValueError("v2 preflight is not a hard negative")
    if preflight.get("status") != "cpu_native_preflight_failed_hard_audit":
        raise ValueError("v2 preflight status is not closed negative")
    fields = read_binary_vtk(BOUND)["point_data"]
    vtk = read_binary_vtk(BOUND)
    summary = summarize(vtk["points"], fields["Mk"], fields["Normal"], fields["NormalSize"])
    if summary["zero_boundnor_count"] != preflight["native_initial"]["zero_boundnor_count"]:
        raise ValueError("v2 Bound.vtk zero count disagrees with preflight")
    by_mk = {int(row["mk"]): row for row in summary["mk_partitions"]}
    evidence = {
        "schema": SCHEMA,
        "status": "completed_negative_result",
        "family": "F2",
        "scope_id": "F2_distributed_submerged_slot_transfer_x_v1",
        "revision_id": "F2_distributed_slot_gate_normal_layers_v2",
        "case_id": preflight["case_id"],
        "qualification_claim": "none",
        "T1_numerical": False,
        "matrix_credit": 0,
        "failure_class": "cpu_native_zero_boundnor_and_normal_size_after_second_normal_hypothesis",
        "preflight": {"status": preflight["status"], "preflight_pass": False, "generated_counts": preflight["generated_counts"], "native_initial": preflight["native_initial"], "mass_contract": preflight["mass_contract"]},
        "partition": summary,
        "observed_v1_to_v2": {"v1_zero_normal_count": 124608, "v2_zero_normal_count": summary["zero_boundnor_count"], "reduction": 124608 - summary["zero_boundnor_count"], "v2_outer_mk17_zero_count": by_mk[17]["zero_boundnor_count"], "v2_gate_mk18_zero_count": by_mk[18]["zero_boundnor_count"]},
        "route_decision": {"normal_hypotheses_exhausted": True, "same_input_retry": False, "new_v3_authorized": False, "threshold_relaxation": False, "solver_authorized": False, "qualification_credit": 0, "next_action": "close this distributed-slot route; select a different physical family or obtain a separately reviewed hypothesis"},
        "execution_controls": {"gencase_invoked": True, "native_decoder_invoked": True, "solver_invoked": False, "gpu_invoked": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "matrix_submission": False, "qualification_credit": 0},
        "hash_bindings": {"preflight": ref(PREFLIGHT, "v2 CPU/native negative preflight"), "bound_vtk": ref(BOUND, "v2 boundary normal field"), "generated_xml": ref(XML, "v2 particle identity XML"), "audit_implementation": ref(Path(__file__), "v2 negative evidence audit")},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# F2 distributed-slot normal repair v2 negative evidence", "", "Status: **hard negative; the two permitted normal-construction hypotheses are exhausted; zero T1 credit**.", "", f"The fresh v2 Definition generated {preflight['generated_counts']['boundary_particles']:,} boundary and {preflight['generated_counts']['fluid_particles']:,} fluid particles. Source mass error was {preflight['mass_contract']['relative_error']:.6%}, but {summary['zero_boundnor_count']:,} BoundNor and NormalSize entries remained zero: Mk17 outer={by_mk[17]['zero_boundnor_count']:,}, Mk18 gate={by_mk[18]['zero_boundnor_count']:,}.", "", "The v2 layer-mirroring hypothesis reduced the zero-normal count from 124,608 to 76,095 but did not satisfy the fixed zero gate. The route is closed; no v3 or same-input retry is authorized.", "", "No solver, GPU, queue, ledger, registry, matrix, or qualification credit was used.", "", "## Hash closure", ""]
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
    value = audit(args.output, args.report)
    print(json.dumps({"status": value["status"], "zero_boundnor_count": value["partition"]["zero_boundnor_count"], "normal_hypotheses_exhausted": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
