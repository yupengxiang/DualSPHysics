#!/usr/bin/env python3
"""Freeze the F5 third-T1 route after its two geometry repairs fail.

This is a read-only lineage audit.  It consumes the already recorded F5
proposal, root reviews, CPU/native preflight receipts, and negative-anchor
evidence.  It deliberately does not create a new Definition, invoke GenCase
or a native decoder, or touch solver, GPU, queue, registry, ledger, matrix,
or denominator state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
F5_ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1"
OUTPUT = LAB / "campaigns/core-v1/evidence/f5-wave-runup-third-t1-route-closed-no-new-hypothesis-v1.json"
REPORT = LAB / "reports/F5-WAVE-RUNUP-THIRD-T1-ROUTE-CLOSED-2026-09-21.zh-CN.md"
CREATED_AT = "2026-09-21T02:00:00Z"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(LAB))


def binding(path: Path, role: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": rel(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _evidence_paths() -> dict[str, tuple[Path, str]]:
    return {
        "proposal": (
            F5_ROOT / "geometry-repair-proposal-audit-v1.json",
            "proposal-only F5 geometry hypothesis audit",
        ),
        "failure_summary": (
            F5_ROOT / "failure-summary-v1.json",
            "authoritative F5 v3/v4 scientific failure and candidate closure",
        ),
        "v3_root_review": (
            F5_ROOT / "root-review-receipt-v1.json",
            "v3 explicit-void geometry root review",
        ),
        "v3_contract": (
            F5_ROOT / "input/geometry-repair-contract-v1.json",
            "v3 explicit-void input/output contract",
        ),
        "v3_preflight": (
            F5_ROOT / "preflight-v3/preflight.json",
            "v3 CPU/native frame-0 geometry result",
        ),
        "v4_root_review": (
            F5_ROOT / "autofill-bound-root-review-v1.json",
            "v4 official-autofill geometry root review",
        ),
        "v4_contract": (
            F5_ROOT / "v4-input/geometry-autofill-bound-contract-v1.json",
            "v4 official-autofill input/output contract",
        ),
        "v4_preflight": (
            F5_ROOT / "preflight-v4/preflight.json",
            "v4 CPU/native frame-0 geometry result",
        ),
        "anchor_negative": (
            LAB / "campaigns/core-v1/evidence/f5-wave-runup-third-t1-anchor-negative-evidence-v1.json",
            "prior sampled solver-anchor scientific negative evidence",
        ),
    }


def _validate_inputs(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    proposal = records["proposal"]
    failure = records["failure_summary"]
    v3 = records["v3_preflight"]
    v4 = records["v4_preflight"]
    v3_review = records["v3_root_review"]
    v4_review = records["v4_root_review"]
    negative = records["anchor_negative"]

    if proposal["status"] != "proposal_only_root_review_required":
        raise AssertionError("proposal is no longer proposal-only")
    if proposal["qualification_claim"] != "none" or proposal["matrix_credit"] != 0:
        raise AssertionError("proposal carries qualification credit")
    if failure["status"] != "f5_candidate_closed_after_two_independent_geometry_repairs":
        raise AssertionError("F5 failure summary is not the authoritative closure")
    if failure["qualified"] or failure["matrix_credit"] != 0:
        raise AssertionError("F5 failure summary is not zero-credit")
    if failure["fixed_denominator"] != {
        "rows": 15,
        "failed_rows_retained": True,
        "same_input_retry": False,
        "survivor_renormalization": False,
    }:
        raise AssertionError("F5 denominator/retry policy changed")

    for version, preflight, case_id in (
        ("v3", v3, "F5_wave_runup_q0p50_dp0p0075_geomrepair_v3"),
        ("v4", v4, "F5_wave_runup_q0p50_dp0p0075_geomrepair_v4"),
    ):
        if preflight["case_id"] != case_id:
            raise AssertionError(f"{version} case identity mismatch")
        if preflight["status"] != "cpu_native_preflight_failed_geometry_repair_gate":
            raise AssertionError(f"{version} is not a scientific geometry failure")
        if preflight["preflight_pass"]:
            raise AssertionError(f"{version} unexpectedly passed")
        geometry = preflight["geometry_repair"]
        if geometry["slope_endpoint_inside_count"] != 0:
            raise AssertionError(f"{version} slope count changed")
        if geometry["blocks_endpoint_inside_count"] != 1:
            raise AssertionError(f"{version} block endpoint count changed")
        if geometry["pass"]:
            raise AssertionError(f"{version} geometry gate changed")
        if preflight["hard_gates"]["frame0_fluid_endpoint_inside_blocks"] is not False:
            raise AssertionError(f"{version} hard gate is not closed")
        controls = preflight["execution_controls"]
        if any(controls[key] for key in ("solver_invoked", "gpu_started")):
            raise AssertionError(f"{version} unexpectedly started solver/GPU")
        if any(controls[key] != 0 for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "matrix_mutation")):
            raise AssertionError(f"{version} mutated protected state")

    for name, review in (("v3", v3_review), ("v4", v4_review)):
        decision = review["review_decision"]
        if decision["authorized_cpu_native_preflight"] is not True:
            raise AssertionError(f"{name} root review did not authorize its recorded preflight")
        if decision["exactly_one_preflight"] is not True:
            raise AssertionError(f"{name} root review is not single-preflight")
        for key in ("authorized_solver", "authorized_gpu", "authorized_queue", "authorized_registry", "authorized_ledger", "authorized_matrix"):
            if decision[key] is not False:
                raise AssertionError(f"{name} root review opened {key}")

    if negative["qualified"] or negative["T1_numerical"] or negative["matrix_credit"] != 0:
        raise AssertionError("prior anchor negative evidence is not frozen as zero-credit")
    if negative["hard_integrity"]["pass"]:
        raise AssertionError("prior anchor negative evidence unexpectedly passed")

    return {
        "v3": {
            "case_id": v3["case_id"],
            "hypothesis": failure["v3"]["hypothesis"],
            "status": v3["status"],
            "blocks_endpoint_inside_count": v3["geometry_repair"]["blocks_endpoint_inside_count"],
            "fluid_first_id": v3["geometry_repair"]["fluid_first_id"],
            "fluid_particles": v3["geometry_repair"]["fluid_particles"],
            "failure_class": "frame0_fluid_endpoint_inside_transformed_blocks",
        },
        "v4": {
            "case_id": v4["case_id"],
            "hypothesis": failure["v4"]["hypothesis"],
            "status": v4["status"],
            "blocks_endpoint_inside_count": v4["geometry_repair"]["blocks_endpoint_inside_count"],
            "fluid_first_id": v4["geometry_repair"]["fluid_first_id"],
            "fluid_particles": v4["geometry_repair"]["fluid_particles"],
            "failure_class": "frame0_fluid_endpoint_inside_transformed_blocks",
        },
        "prior_anchor": {
            "scientific_failure_class": negative["scientific_failure_class"],
            "sampled_entity_penetration_particle_frames": negative["hard_integrity"]["observed_sampled"]["entity_penetration_particle_frames"],
            "sampled_saved_chord_crossing_count": negative["hard_integrity"]["observed_sampled"]["saved_chord_crossing_count"],
        },
    }


def _render_report(
    bindings: dict[str, dict[str, Any]],
    comparison: dict[str, Any],
) -> str:
    return f"""# F5 第三个 T1 候选路线关闭审计（2026-09-21）

结论：`F5_prescribed_wave_runup_x_v1` 当前关闭，审计范围内没有一个证据支持且物理机制真正独立的新假设。`qualification_claim=none`、`qualified=false`、`T1_numerical=false`、`matrix_credit=0`；本次审计没有写新 Definition，也没有运行 CPU/GenCase/native preflight。

proposal 给出的 H1 由 v3 具体测试：在不改变斜坡、块体、活塞、`q=0.5`、`dp=0.0075 m`、域边界和输出 cadence 的条件下，先用 `setmkvoid`/`autofill` 建立闭体排除，再重画物理 STL。v3 的 GenCase 和 native decode 成功，但 frame 0 的 fluid-only 几何硬门仍发现 1 个块体内部 endpoint（`fluid_first_id={comparison['v3']['fluid_first_id']}`），所以 H1 失败。

v4 使用另一种官方 materialization：每个 watertight STL 只做一次 `setmkbound` 后的 `drawfilestl autofill=true`。它仍保持同一物理几何和输入参数，且同样得到 1 个 frame-0 fluid block endpoint（`fluid_first_id={comparison['v4']['fluid_first_id']}`）。因此 v3/v4 是两种离散几何物化修复，不能被解释为新的波浪、接触、边界拓扑或观测物理机制；两者的共同科学失败保留在 authoritative failure summary 中。

proposal 的 H2 只提出 source-STL 与离散 MkCells 之间的接触带分类诊断。它明确不能放宽 exact fluid endpoint 或 saved-chord 硬门，也没有提供可通过该硬门的新物理机制。已有 v2 anchor 的只读抽样也记录了 `{comparison['prior_anchor']['sampled_entity_penetration_particle_frames']}` 个 entity-penetration particle frames 和 `{comparison['prior_anchor']['sampled_saved_chord_crossing_count']}` 个 saved-chord crossings；这些 negative evidence 不被删除、不重解释为资格结果。

本次 receipt 只冻结谱系和关闭动作：

- v3/v4 的科学失败保留；同一输入不重试，旧 v2 Definition/XML/BI4/trajectory/output stem 不复用。
- solver、GPU、queue、job、registry、ledger、T1/T2 分母和 matrix 均没有 mutation；固定 15 行分母继续保留失败行，禁止 survivor renormalization。
- 只有在未来出现新的、可证伪且与现有两种 geometry materialization 机制独立的 F5 物理假设，并经过新的 root review 后，才可以重新开启路线。此 receipt 本身不授权任何 preflight 或 runtime。

证据 hash contract：

""" + "\n".join(
        f"- `{name}`：`{item['path']}`，SHA-256 `{item['sha256']}`。"
        for name, item in bindings.items()
    ) + "\n"


def build_contract() -> dict[str, Any]:
    paths = _evidence_paths()
    records = {name: load(path) for name, (path, _) in paths.items()}
    comparison = _validate_inputs(records)

    base_bindings = {
        name: binding(path, role) for name, (path, role) in paths.items()
    }
    base_bindings["implementation"] = binding(
        Path(__file__), "read-only F5 route-closure implementation"
    )
    test_path = LAB / "tests/test_f5_wave_runup_route_closed_audit_v1.py"
    base_bindings["test"] = binding(test_path, "route-closure regression test")

    # Write the report before the JSON so the JSON can bind the report hash
    # without creating a circular self-hash.  The report intentionally does
    # not claim that its own hash is part of its body.
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(_render_report(base_bindings, comparison), encoding="utf-8")
    base_bindings["report"] = binding(REPORT, "Chinese route-closure report")

    return {
        "schema": "core.f5.third_t1.route_closed_no_new_hypothesis.v1",
        "created_at_utc": CREATED_AT,
        "record_id": "f5-wave-runup-third-t1-route-closed-no-new-hypothesis-v1",
        "status": "f5_route_closed_no_new_hypothesis",
        "family": "F5",
        "scope_id": "F5_prescribed_wave_runup_x_v1",
        "qualification_only": True,
        "qualification_claim": "none",
        "qualified": False,
        "T1_numerical": False,
        "T2_numerical": False,
        "matrix_credit": 0,
        "candidate_status": "closed",
        "decision": "stop_f5_until_independent_physical_hypothesis",
        "independent_hypothesis_audit": {
            "status": "none_found_in_audited_f5_lineage",
            "new_physical_hypothesis_count": 0,
            "audited_hypotheses": [
                {
                    "id": "H1_missing_solid_exclusion_or_fill_ordering",
                    "status": "tested_and_failed_by_v3",
                    "mechanism_class": "geometry_materialization",
                    "result": comparison["v3"],
                },
                {
                    "id": "H2_strict_stl_contact_band_classification",
                    "status": "diagnostic_only_no_release_credit",
                    "mechanism_class": "classification_diagnostic",
                    "result": "Cannot waive exact fluid endpoint or saved-chord gates.",
                },
                {
                    "id": "H2b_official_autofill_boundary_materialization",
                    "status": "tested_and_failed_by_v4",
                    "mechanism_class": "geometry_materialization",
                    "result": comparison["v4"],
                },
            ],
            "closure_reason": [
                "v3 and v4 preserve the same transformed physical STL, motion, q, dp, domain, and cadence; they only change discrete materialization.",
                "Both exact frame-0 fluid-only gates leave one block endpoint inside the transformed block STL.",
                "No audited F5 artifact proposes a distinct wave/contact/topology mechanism with a falsifiable prediction beyond those two repairs.",
            ],
        },
        "scientific_failure_preserved": {
            "v3": comparison["v3"],
            "v4": comparison["v4"],
            "prior_anchor": comparison["prior_anchor"],
            "same_input_retry": False,
            "failure_summary_is_authoritative": True,
        },
        "fixed_denominator": {
            "planned_rows": 15,
            "failed_rows_retained": True,
            "survivor_renormalization": False,
            "denominator_mutation": 0,
            "matrix_mutation": 0,
            "T1_T2_denominator_mutation": 0,
        },
        "reuse_policy": {
            "new_definition_written": False,
            "new_input_identity_materialized": False,
            "old_v2_definition_reused": False,
            "old_v2_generated_xml_reused": False,
            "old_v2_bi4_reused": False,
            "old_v2_trajectory_reused": False,
            "old_v2_output_stem_reused": False,
            "v3_v4_retry": False,
            "forbidden_reuse": [
                "fresh-definition-v2/F5_wave_runup_q0p50_dp0p0075_Def.xml",
                "fresh-definition-v2/preflight-v2/generated/F5_wave_runup_q0p50_dp0p0075_v2.bi4",
                "f5-wave-runup-third-t1-q05-dp0075-v2-protected-gpu-anchor/*",
                "data-official/O5_wave_runup.h5",
                "data-official/O5_wave_runup_refined.h5",
            ],
        },
        "execution_controls": {
            "read_only_audit": True,
            "definition_written": False,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "job_mutation": 0,
            "attempt_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_mutation": 0,
            "qualification_credit": 0,
        },
        "next_step": {
            "decision": "route_closed",
            "required_before_reopening": [
                "A new root-level scientific hypothesis independent of v3/v4 geometry materialization must be written and falsifiable.",
                "A new candidate identity and root review must be approved before any file materialization or preflight.",
            ],
            "forbidden_now": [
                "Do not rerun v2, v3, or v4.",
                "Do not start solver, GPU, queue, registry, ledger, T1, T2, or matrix actions.",
            ],
        },
        "hash_bindings": base_bindings,
    }


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    if value["schema"] != "core.f5.third_t1.route_closed_no_new_hypothesis.v1":
        raise AssertionError("schema mismatch")
    if value["status"] != "f5_route_closed_no_new_hypothesis":
        raise AssertionError("route is not closed")
    if value["independent_hypothesis_audit"]["new_physical_hypothesis_count"] != 0:
        raise AssertionError("a new physical hypothesis was unexpectedly admitted")
    if value["qualification_claim"] != "none" or value["matrix_credit"] != 0:
        raise AssertionError("route closure is not zero-credit")
    if value["fixed_denominator"]["planned_rows"] != 15:
        raise AssertionError("fixed denominator changed")
    controls = value["execution_controls"]
    if not controls["read_only_audit"] or any(
        controls[key]
        for key in ("definition_written", "gencase_invoked", "native_decode_invoked", "solver_invoked", "gpu_started")
    ):
        raise AssertionError("route-closure audit performed a computation")
    if any(controls[key] != 0 for key in ("queue_mutation", "job_mutation", "attempt_mutation", "registry_mutation", "ledger_mutation", "matrix_mutation", "qualification_credit")):
        raise AssertionError("route-closure audit mutated protected state")

    for name, item in value["hash_bindings"].items():
        path_on_disk = LAB / item["path"]
        if sha256(path_on_disk) != item["sha256"]:
            raise AssertionError(f"hash mismatch: {name}")
        if path_on_disk.stat().st_size != item["bytes"]:
            raise AssertionError(f"size mismatch: {name}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="verify the committed receipt without writing")
    args = parser.parse_args()
    if args.verify:
        verify()
        print(json.dumps({"status": "verified", "path": rel(OUTPUT)}, indent=2))
        return 0
    value = build_contract()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    verify()
    print(json.dumps({"status": value["status"], "path": rel(OUTPUT), "sha256": sha256(OUTPUT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
