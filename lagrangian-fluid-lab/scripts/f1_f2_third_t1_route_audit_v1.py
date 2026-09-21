#!/usr/bin/env python3
"""Build a read-only, hash-bound F1/F2 third-T1 route audit.

The audit consumes existing qualification, negative-anchor, denominator, and
proposal records.  It never opens a trajectory and has no solver, GPU, queue,
ledger, or registry entry point.  Its selected next step is the already
separated F2 submerged-orifice normal-remediation contract, which remains
proposal-only until a separate root review authorizes one CPU/native preflight.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / "campaigns/core-v1/cfd/f1-f2-third-t1-route-audit-v1.json"
REPORT = LAB / "reports/F1-F2-THIRD-T1-ROUTE-AUDIT-2026-09-21.zh-CN.md"


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


def _p(*parts: str) -> Path:
    return LAB.joinpath(*parts)


def build_contract() -> dict[str, Any]:
    f1_eval_path = _p("campaigns/core-v1/cfd/f1-qualification-evaluation.json")
    f1_h2_path = _p("campaigns/core-v1/evidence/f1-h2-mdbc-summary.json")
    f1_negative_path = _p(
        "campaigns/core-v1/evidence/f1-suspended-obstacle-gap-g1-anchor-negative-evidence-v1.json"
    )
    f1_forensics_path = _p("campaigns/core-v1/cfd/f1-canary-forensics.json")

    f2_route_path = _p(
        "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/route-audit-v1.json"
    )
    f2_terminal_matrix_path = _p(
        "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/terminal-matrix-v1.json"
    )
    f2_terminal_denominator_path = _p(
        "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/terminal-failure-denominator-v1.json"
    )
    f2_negative_path = _p(
        "campaigns/core-v1/evidence/f2-receiver-overflow-weir-anchor-negative-evidence-v1.json"
    )

    orifice_root = _p("campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1")
    orifice_candidate_path = orifice_root / "candidate-card-v1.json"
    orifice_matrix_path = orifice_root / "fixed-matrix-v1.json"
    orifice_denominator_path = orifice_root / "failure-denominator-v1.json"
    orifice_lineage_path = orifice_root / "lineage-clarification-v1.json"
    orifice_failed_preflight_path = orifice_root / "anchor-q0p5-dp0p0075/preflight.json"
    v2_root = orifice_root / "normal-remediation-v2"
    v2_candidate_path = v2_root / "normal-remediation-candidate-v2.json"
    v2_contract_path = v2_root / "root-review-only-contract-v2.json"
    v2_definition_contract_path = v2_root / "fresh-definition-contract-v2.json"
    v2_definition_proposal_path = v2_root / "fresh-definition-proposal-v2.json"
    v2_root_receipt_path = v2_root / "root-review-receipt-v3.json"
    v2_preflight_contract_path = v2_root / "preflight-contract-v3.json"

    f1_eval = load(f1_eval_path)
    f1_h2 = load(f1_h2_path)
    f1_negative = load(f1_negative_path)
    f2_route = load(f2_route_path)
    f2_terminal = load(f2_terminal_matrix_path)
    f2_terminal_denominator = load(f2_terminal_denominator_path)
    f2_negative = load(f2_negative_path)
    orifice_candidate = load(orifice_candidate_path)
    orifice_matrix = load(orifice_matrix_path)
    orifice_denominator = load(orifice_denominator_path)
    orifice_lineage = load(orifice_lineage_path)
    orifice_failed_preflight = load(orifice_failed_preflight_path)
    v2_candidate = load(v2_candidate_path)
    v2_contract = load(v2_contract_path)
    v2_definition_contract = load(v2_definition_contract_path)
    v2_definition_proposal = load(v2_definition_proposal_path)
    v2_root_receipt = load(v2_root_receipt_path)
    v2_preflight_contract = load(v2_preflight_contract_path)

    # The route choice is deliberately based on existing evidence, not on a
    # new scientific run.  Keep this proof local so a tampered input cannot
    # silently turn a negative route into a candidate.
    assert f1_eval["qualified"] is False
    assert f1_eval["T1_numerical"] is False
    assert f1_h2["hard_integrity_pass"] is False
    assert f1_negative["qualified"] is False
    assert f1_negative["matrix_credit"] == 0
    assert f2_terminal["qualified"] is False
    assert f2_terminal["matrix_credit"] == 0
    assert f2_terminal_denominator["credit"] == 0
    assert f2_negative["qualified"] is False
    assert orifice_candidate["qualified"] is False
    assert orifice_candidate["matrix_credit"] == 0
    assert orifice_matrix["denominator"]["planned"] == 15
    assert orifice_matrix["denominator"]["executed"] == 0
    assert orifice_denominator["credit"] == 0
    assert orifice_failed_preflight["preflight_pass"] is False
    assert orifice_failed_preflight["native_initial"]["zero_boundary_normals"] > 0
    assert v2_root_receipt["authorized_for_one_fresh_cpu_native_preflight"] is False
    assert v2_root_receipt["static_review"]["fresh_definition_runtime_invoked"] is False
    assert v2_root_receipt["static_review"]["fresh_native_bi4_present"] is False
    assert v2_preflight_contract["proposal_only"] is True
    assert v2_preflight_contract["authorized_now"] is False

    evidence = {
        "f1_qualification": binding(f1_eval_path, "F1 qualification evaluation"),
        "f1_h2_negative_summary": binding(f1_h2_path, "F1 H1/H2 repair stop summary"),
        "f1_suspended_obstacle_negative": binding(
            f1_negative_path, "F1 completed hard-integrity negative anchor"
        ),
        "f1_canary_forensics": binding(f1_forensics_path, "F1 canary forensics"),
        "f2_receiver_route_audit": binding(f2_route_path, "F2 receiver/weir route audit"),
        "f2_receiver_terminal_matrix": binding(
            f2_terminal_matrix_path, "F2 receiver/weir terminal matrix"
        ),
        "f2_receiver_terminal_denominator": binding(
            f2_terminal_denominator_path, "F2 receiver/weir terminal denominator"
        ),
        "f2_receiver_negative_anchor": binding(
            f2_negative_path, "F2 receiver/weir hard-integrity negative anchor"
        ),
        "selected_orifice_candidate": binding(orifice_candidate_path, "independent F2 candidate"),
        "selected_orifice_matrix": binding(orifice_matrix_path, "independent F2 15-row matrix"),
        "selected_orifice_denominator": binding(
            orifice_denominator_path, "independent F2 zero-credit denominator"
        ),
        "selected_orifice_lineage": binding(orifice_lineage_path, "independent F2 lineage"),
        "failed_orifice_preflight": binding(
            orifice_failed_preflight_path, "failed original F2 orifice CPU/native preflight"
        ),
        "v2_normal_remediation_candidate": binding(
            v2_candidate_path, "fresh normal-remediation candidate"
        ),
        "v2_normal_remediation_contract": binding(
            v2_contract_path, "fresh normal-remediation root-review-only contract"
        ),
        "v2_definition_contract": binding(
            v2_definition_contract_path, "fresh literal Definition static contract"
        ),
        "v2_definition_proposal": binding(
            v2_definition_proposal_path, "fresh literal Definition proposal"
        ),
        "v3_definition_root_receipt": binding(
            v2_root_receipt_path, "fresh Definition static root receipt"
        ),
        "v3_cpu_native_preflight_contract": binding(
            v2_preflight_contract_path, "future CPU/native preflight contract"
        ),
        "implementation": binding(
            Path(__file__), "read-only route audit implementation"
        ),
        "test": binding(
            LAB / "tests/test_f1_f2_third_t1_route_audit_v1.py",
            "read-only route audit regression test",
        ),
    }

    selected = {
        "family": "F2",
        "scope_id": "F2_submerged_orifice_transfer_v1",
        "revision_id": "F2_submerged_orifice_normal_remediation_v2",
        "candidate_id": v2_candidate["candidate_id"],
        "status": "proposal_only_root_review_required",
        "decision": "select_independent_f2_submerged_orifice_normal_remediation",
        "reason": [
            "F1 has an explicit H1/H2 repair stop and a completed suspended-obstacle hard-integrity negative anchor.",
            "The F2 receiver/weir anchor is terminal hard-integrity failure plus event censoring; repeating that input is prohibited.",
            "The submerged-orifice route changes the topology to a stationary reservoir and real underflow aperture, and retains a separate 15-row denominator.",
            "Its original q=.5 CPU/native input failed only the zero-normal gate; the v2 fresh Definition is statically hash-reviewed and is the smallest auditable next step.",
        ],
        "required_review_before_action": "separately review v3 static receipt and authorize exactly one fresh CPU/native preflight",
        "future_case_id": v2_preflight_contract["case_id"],
        "future_output_stem": v2_preflight_contract["fresh_output"]["generated_prefix"],
        "future_cpu_native_gates": v2_preflight_contract["hard_gates"],
        "future_execution_order": [
            "read fresh literal v2 Definition and verify its binding",
            "run CPU GenCase only into the new normalremediation_v2 output stem",
            "decode native XML/BI4 and evaluate zero BoundNor, finite arrays, IDs, mass, and endpoint gates",
            "write a zero-credit result; stop before solver/GPU/queue/ledger/registry",
        ],
        "authorization_now": {
            "definition_writer": False,
            "cpu_gencase": False,
            "native_decode": False,
            "solver": False,
            "gpu": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
            "qualification_credit": 0,
        },
        "denominator": {
            "planned": 15,
            "executed": 0,
            "passed": 0,
            "failed": 0,
            "event_censored": 0,
            "unattempted": 15,
            "credit": 0,
            "same_input_retry": False,
            "threshold_relaxation": False,
            "survivor_renormalization": False,
        },
        "blockers": [
            "The original q=.5 orifice preflight has 63161 zero boundary normals and therefore failed the hard input gate.",
            "The v2 fresh Definition has a static review only; no fresh generated XML/BI4 exists for v2.",
            "The v3 root receipt explicitly denies CPU/native authority; a separate root review is required.",
            "No solver, GPU, queue, ledger, registry, or T1 qualification action is authorized by this audit.",
        ],
        "old_failed_input_reused": False,
        "old_failed_trajectory_reused": False,
    }

    return {
        "schema": "core.third_t1.f1_f2_route_audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "proposal_only_selected_independent_f2_after_f1_f2_negative_audit",
        "review_order": ["F1", "F2_receiver_overflow_weir", "F2_submerged_orifice"],
        "core_gate": {
            "current_registered_t1_families": ["F3", "F4"],
            "required_t1_family_count": 3,
            "third_t1_family_established": False,
            "qualification_credit_added": 0,
            "core_gate_changed": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
        },
        "f1_audit": {
            "status": "closed_for_current_repair_lineage",
            "qualified": False,
            "T1_numerical": False,
            "qualification_claim": f1_eval["qualification_claim"],
            "h1_h2_decision": f1_h2["decision"],
            "h1_canary_hard_integrity": f1_eval["canary"]["hard_integrity_pass"],
            "suspended_obstacle_hard_integrity": f1_negative["hard_integrity"]["pass"],
            "suspended_obstacle_event_complete": f1_negative["event_window"]["complete"],
            "same_input_retry": f1_negative["execution_constraints"]["same_input_retry"],
            "matrix_credit": f1_negative["matrix_credit"],
            "blocker": "H1/H2 repair mechanism is explicitly stopped after hard-integrity failures; no same-class F1 retry is proposed.",
            "evidence": {
                "qualification": evidence["f1_qualification"],
                "h1_h2_summary": evidence["f1_h2_negative_summary"],
                "suspended_obstacle": evidence["f1_suspended_obstacle_negative"],
                "forensics": evidence["f1_canary_forensics"],
            },
        },
        "f2_receiver_overflow_weir_audit": {
            "status": "terminal_anchor_negative_route_preserved",
            "qualified": False,
            "qualification_claim": f2_route.get("matrix_and_credit", {}).get("qualification_claim", "none"),
            "planned": f2_terminal["denominator"]["planned"],
            "executed": f2_terminal["denominator"]["executed"],
            "passed": f2_terminal["denominator"]["passed"],
            "failed": f2_terminal["denominator"]["failed"],
            "event_censored": f2_terminal["denominator"]["event_censored"],
            "unattempted": f2_terminal["denominator"]["unattempted"],
            "matrix_credit": f2_terminal["matrix_credit"],
            "hard_integrity_pass": f2_negative["hard_integrity"]["pass"],
            "event_window_complete": f2_negative["event_window"]["complete"],
            "endpoint_violation_particle_frames": f2_negative["hard_integrity"]["endpoint_violation_particle_frames"],
            "weir_penetration_particle_frames": f2_negative["hard_integrity"]["obstacle_penetration_particle_frames"],
            "saved_chord_crossing_count": f2_negative["hard_integrity"]["saved_chord_crossing_count"],
            "same_input_retry": f2_terminal_denominator["preservation"]["same_input_retry"],
            "blocker": "The registered q=.5 receiver/weir anchor failed hard integrity and was event-censored; it is retained with zero credit and is not retried.",
            "evidence": {
                "route_audit": evidence["f2_receiver_route_audit"],
                "terminal_matrix": evidence["f2_receiver_terminal_matrix"],
                "terminal_denominator": evidence["f2_receiver_terminal_denominator"],
                "negative_anchor": evidence["f2_receiver_negative_anchor"],
            },
        },
        "selected_next_step": selected,
        "hash_bindings": evidence,
        "interpretation_boundary": "read-only route audit and proposal contract; it changes no scientific denominator, registry, ledger, or Core gate",
    }


def render_report(contract: dict[str, Any]) -> str:
    selected = contract["selected_next_step"]
    f1 = contract["f1_audit"]
    f2 = contract["f2_receiver_overflow_weir_audit"]
    lines = [
        "# F1/F2 第三 T1 家族路线审计（2026-09-21）",
        "",
        "本次只读审计先核验 F1，再核验 F2 receiver/overflow-weir。F1 的 H1/H2 修复线已有明确停止结论，悬空障碍物 anchor 也以完整事件窗口记录了 hard-integrity 失败；F2 receiver/weir 的 q=.5 anchor 同样保留 hard-integrity 失败和 event-censored 结果。因此没有重跑同一输入，也没有把失败者从分母删除。",
        "",
        f"选择的最小下一步是独立拓扑的 F2 submerged-orifice normal-remediation v2 静态合同：原始 q=.5 CPU/native 输入有 63161 个 zero boundary normals，v2 新 Definition 已完成 hash-bound 静态审查，但还没有新 v2 XML/BI4，且 v3 root receipt 明确未授权 CPU/native。下一步只能先获得单独 root review，再考虑一个新 output stem 的 CPU/native preflight；本合同不授权执行。",
        "",
        "## 现有路线结论",
        "",
        f"- F1：`qualified=false`、`T1_numerical=false`；H1 canary hard-integrity={f1['h1_canary_hard_integrity']}，F1 G1 anchor hard-integrity={f1['suspended_obstacle_hard_integrity']}，事件窗口虽完整也不能挽救 hard failure。当前 repair lineage 的 blocker 是 H1/H2 stop/no same-class retry。",
        f"- F2 receiver/weir：15 行中 `executed={f2['executed']}`、`failed={f2['failed']}`、`event_censored={f2['event_censored']}`、`unattempted={f2['unattempted']}`、`matrix_credit={f2['matrix_credit']}`；hard-integrity={f2['hard_integrity_pass']}，event complete={f2['event_window_complete']}，weir penetration particle frames={f2['weir_penetration_particle_frames']}。该 route 关闭为负证据，不重试。",
        "",
        "## 选定合同边界",
        "",
        f"- candidate：`{selected['candidate_id']}`，case：`{selected['future_case_id']}`。新 output stem：`{selected['future_output_stem']}`。",
        "- 先审查 v3 static root receipt；本轮 `definition_writer/cpu_gencase/native_decode/solver/gpu/queue/ledger/registry` 全部关闭，资格 credit=0。",
        "- 若未来得到独立授权，只能按 fixed hard gates 检查 zero BoundNor、normal size、finite/ID、native mass 和 wall/gate endpoint；失败或 event-censored 继续留在 15-row denominator，不能放宽阈值、重标输入或 survivor renormalization。",
        "",
        "## 产物与 SHA-256",
        "",
        f"- audit/contract：`campaigns/core-v1/cfd/f1-f2-third-t1-route-audit-v1.json`（运行脚本后读取该文件计算 SHA）。",
        f"- implementation：`{contract['hash_bindings']['implementation']['path']}`，SHA `{contract['hash_bindings']['implementation']['sha256']}`。",
        "- contract 的 `hash_bindings` 保存 F1 资格/失败证据、F2 receiver terminal denominator、orifice parent matrix/denominator、v2 candidate/Definition/root receipt/preflight contract 的当前 SHA 和字节数。",
        "",
        "Core gate 结论：`third_t1_family_established=false`、`qualification_credit_added=0`、`core_gate_changed=false`；registry/ledger mutation 均为 0。",
        "",
    ]
    return "\n".join(lines)


def write_outputs(output: Path = OUTPUT, report: Path = REPORT) -> dict[str, Any]:
    contract = build_contract()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(contract), encoding="utf-8")
    return contract


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    if value["schema"] != "core.third_t1.f1_f2_route_audit.v1":
        raise AssertionError("wrong schema")
    if value["core_gate"]["core_gate_changed"] is not False:
        raise AssertionError("Core gate changed")
    if value["selected_next_step"]["authorization_now"]["qualification_credit"] != 0:
        raise AssertionError("unexpected credit")
    for item in value["hash_bindings"].values():
        target = LAB / item["path"]
        if sha256(target) != item["sha256"] or target.stat().st_size != item["bytes"]:
            raise AssertionError(f"stale binding: {item['path']}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify(args.output)
        print(json.dumps({"verified": True, "path": str(args.output)}, ensure_ascii=False))
        return
    write_outputs(args.output, args.report)
    verify(args.output)
    print(json.dumps({"written": str(args.output), "report": str(args.report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
