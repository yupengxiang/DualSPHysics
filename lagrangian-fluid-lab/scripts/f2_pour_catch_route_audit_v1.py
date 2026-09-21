#!/usr/bin/env python3
"""Build a read-only F2 pour/catch route decision and root-review gap audit.

The selected route is a new, fixed-receiver ballistic-catch hypothesis.  It is
deliberately separate from the closed submerged-slot route and from the failed
v1 receiver anchor.  This module only reads existing JSON/Markdown evidence,
recomputes SHA-256 bindings, and writes proposal/audit records.  It has no
GenCase, native decoder, solver, GPU, queue, ledger, registry, or matrix
submission entry point.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROUTE_OUTPUT = LAB / "campaigns/core-v1/cfd/f2-pour-catch-route-audit-v1.json"
CANDIDATE_OUTPUT = LAB / "campaigns/core-v1/cfd/f2-pour-catch-candidate-card-v2.json"
GAP_OUTPUT = LAB / "campaigns/core-v1/cfd/f2-pour-catch-root-review-gap-audit-v1.json"
REPORT_OUTPUT = LAB / "reports/F2-POUR-CATCH-ROUTE-AUDIT-2026-09-21.zh-CN.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def local(relative: str) -> Path:
    path = LAB / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def ref(relative: str, role: str) -> dict[str, Any]:
    path = local(relative)
    return {
        "path": relative,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def _row(index: int, q: float, dp: float, kind: str, suffix: str = "") -> dict[str, Any]:
    q_token = f"{q:.2f}".replace(".", "p")
    dp_token = f"{dp:.4f}".replace(".", "p")
    return {
        "index": index,
        "q": q,
        "dp_m": dp,
        "design_cell": kind,
        "case_id": f"CORE_F2_RECEIVER_BALLISTIC_CATCH_RELEASE010_q{q_token}_dp{dp_token}{suffix}",
        "status": "proposal_only_unmaterialized",
    }


def build_candidate() -> dict[str, Any]:
    proposal = load(local("campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-proposal-v1.json"))
    preflight = load(local("campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-v1/preflight/preflight.json"))
    postrun = load(local(
        "campaigns/core-v1/runtime/attempts/"
        "f2-static-receiver-ballistic-catch-q05-anchor-infra-retry-v1/"
        "20260921T111854-b642c199de99/product/postrun-audit.json"
    ))

    assert proposal["family"] == "F2"
    assert proposal["qualification_claim"] == "none"
    assert proposal["candidate"]["mechanism_class"] == "stationary_receiver_ballistic_slug_capture"
    assert proposal["fixed_scope_design"]["cell_count"] == 15
    assert preflight["status"] == "cpu_native_preflight_pass"
    assert preflight["matrix_credit"] == 0
    assert postrun["status"] == "raw_solver_complete_scientific_hard_failure"
    assert postrun["hard_integrity_pass"] is False
    assert postrun["run_out_summary"]["excluded_particles"] == 64
    assert postrun["run_out_summary"]["excluded_particles_density"] == 44

    rows: list[dict[str, Any]] = []
    index = 0
    for q in (0.0, 0.5, 1.0):
        for dp in (0.01, 0.0075, 0.005):
            rows.append(_row(index, q, dp, "spatial"))
            index += 1
    for q in (0.25, 0.75):
        for dp in (0.0075, 0.005):
            rows.append(_row(index, q, dp, "held_out", "_heldout"))
            index += 1
    rows.append(_row(index, 0.5, 0.0075, "internal_time", "_internal_time"))
    rows[-1]["temporal_variant"] = "internal_time"
    index += 1
    rows.append(_row(index, 0.5, 0.0075, "native_output", "_native_output"))
    rows[-1]["temporal_variant"] = "native_output"

    return {
        "schema": "core.f2.pour_catch.candidate_card.v2",
        "status": "root_review_only_new_definition_required",
        "family": "F2",
        "scope_id": "F2_receiver_ballistic_catch_release_speed_v2_x_v1",
        "revision_id": "F2_receiver_ballistic_catch_release_speed_v2",
        "candidate_id": "F2_receiver_ballistic_catch_release_speed010_v2",
        "mechanism_class": "stationary_receiver_ballistic_slug_capture",
        "qualification_claim": "none",
        "T1_numerical": False,
        "matrix_credit": 0,
        "hypothesis": {
            "statement": (
                "A fresh finite slug with a lower prescribed release speed (-0.10 m/s) "
                "will reduce the impact impulse that caused density exclusions in the "
                "v1 anchor while retaining gravity-driven receiver contact and destination allocation."
            ),
            "changed_control": "initial_source_velocity_z_m_s",
            "v1_value": -0.20,
            "v2_value": -0.10,
            "all_other_controls_frozen_for_comparison": True,
            "falsifiable": True,
        },
        "topology": {
            "source": "finite free-falling liquid slug",
            "receiver": "fixed open-top basin with closed floor and side walls",
            "aperture_or_crest": False,
            "moving_cup": False,
            "submerged_slot": False,
            "distinct_from_closed_route": True,
        },
        "fresh_input_contract": {
            "new_scope_id": True,
            "new_revision_id": True,
            "new_case_id": True,
            "new_literal_definition_required": True,
            "new_native_output_required": True,
            "source_reuse": False,
            "qualification_inheritance": False,
            "v1_definition_reused": False,
            "v1_generated_xml_reused": False,
            "v1_generated_bi4_reused": False,
            "v1_trajectory_reused": False,
            "v1_output_stem_reused": False,
            "same_input_retry": False,
            "forbidden_sources": [
                "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-v1/input/**",
                "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-v1/preflight/generated/**",
                "campaigns/core-v1/runtime/attempts/f2-static-receiver-ballistic-catch-q05-anchor-*/*",
                "campaigns/core-v1/cfd/f2-distributed-slot-transfer-v1/**",
                "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/**",
            ],
        },
        "planned_matrix": {
            "proposed_rows": 15,
            "rows": rows,
            "parent_scope_denominator_unchanged": True,
            "proposal_only": True,
            "executed": 0,
            "passed": 0,
            "failed": 0,
            "event_censored": 0,
            "unattempted": 15,
            "credit": 0,
            "survivor_renormalization": False,
        },
        "retained_v1_negative": {
            "anchor_case_id": preflight["root_review"]["case_id"],
            "loader_attempt_returncode": 127,
            "repair_attempt_frames": postrun["frame_inventory"]["count"],
            "repair_attempt_excluded_particles": postrun["run_out_summary"]["excluded_particles"],
            "repair_attempt_excluded_particles_density": postrun["run_out_summary"]["excluded_particles_density"],
            "hard_integrity_pass": postrun["hard_integrity_pass"],
            "matrix_credit": postrun["matrix_credit"],
            "same_input_retry": False,
            "reuse_allowed": False,
        },
        "hard_gates_before_any_anchor": {
            "native_ids_unique_and_xml_aligned": True,
            "all_decoded_arrays_finite": True,
            "closed_outer_wall_endpoint_count": 0,
            "closed_receiver_endpoint_and_chord_count": 0,
            "excluded_particles": 0,
            "source_mass_relative_error_max": 0.025,
            "full_window_mass_change_relative_max": 1.0e-8,
            "registered_horizon_s": 1.5,
            "event_window_complete_required": True,
        },
        "root_review_gaps": [
            "freeze the changed release-speed hypothesis and its literal geometry contract",
            "review the new Definition before any CPU/native action",
            "bind a new output stem and verify no v1 asset enters the new scope",
            "define receiver-contact and retained-versus-spill ownership for every q endpoint",
            "authorize at most one fresh CPU/native preflight; a pass is zero-credit",
            "require a second root review before any protected solver anchor",
        ],
        "execution_controls": {
            "read_only_audit": True,
            "definition_writer_invoked": False,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_launched": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
            "matrix_materialized": False,
            "matrix_submitted": False,
        },
        "evidence": {
            "proposal": ref(
                "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-proposal-v1.json",
                "v1 route proposal; reference only",
            ),
            "cpu_native_preflight": ref(
                "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-v1/preflight/preflight.json",
                "v1 input closure; zero credit",
            ),
            "v1_postrun_negative": ref(
                "campaigns/core-v1/runtime/attempts/"
                "f2-static-receiver-ballistic-catch-q05-anchor-infra-retry-v1/"
                "20260921T111854-b642c199de99/product/postrun-audit.json",
                "v1 same-input repair attempt; retained hard failure",
            ),
        },
    }


def build_gap(candidate: dict[str, Any]) -> dict[str, Any]:
    first_attempt = load(local(
        "campaigns/core-v1/runtime/attempts/"
        "f2-static-receiver-ballistic-catch-q05-anchor-v1/"
        "20260921T111451-a4575f1d2a18/product/result.json"
    ))
    postrun = load(local(
        "campaigns/core-v1/runtime/attempts/"
        "f2-static-receiver-ballistic-catch-q05-anchor-infra-retry-v1/"
        "20260921T111854-b642c199de99/product/postrun-audit.json"
    ))
    root_review = load(local(
        "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-v1/root-review-receipt-v1.json"
    ))
    infra_retry = load(local(
        "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-v1/solver-anchor-v1/infra-retry-root-review-v1.json"
    ))

    assert first_attempt["returncode"] == 127
    assert first_attempt["execution_status"] == "raw_solver_failed"
    assert postrun["hard_integrity_pass"] is False
    assert postrun["run_out_summary"]["excluded_particles"] == 64
    assert root_review["fresh_input"]["same_input_retry"] is False
    assert infra_retry["repair"]["scientific_definition_changed"] is False
    assert infra_retry["repair"]["generated_input_changed"] is False

    gaps = [
        {
            "id": "V2_DEFINITION_MISSING",
            "status": "blocking",
            "evidence": "No literal Definition or Definition contract exists for the release-speed v2 candidate.",
            "required": "Root review must approve a new literal Definition with a new case/output identity.",
        },
        {
            "id": "V1_INPUT_CLOSED",
            "status": "blocking",
            "evidence": "The v1 input had loader failure 127, then 64 excluded particles (44 density) after the allowed infrastructure repair.",
            "required": "Do not reuse v1 Definition, generated XML/BI4, trajectory, output stem, or same-input retry.",
        },
        {
            "id": "EVENT_CONTRACT_UNREVIEWED",
            "status": "blocking",
            "evidence": "The v2 receiver-contact and destination-allocation ownership has no root-approved literal observer contract.",
            "required": "Freeze contact, retention/spill, closed-face/chord, and full-window gates before preflight.",
        },
        {
            "id": "CPU_NATIVE_PREFLIGHT_MISSING",
            "status": "blocking",
            "evidence": "The existing CPU/native pass belongs to v1 and cannot be inherited by v2.",
            "required": "After root approval, authorize exactly one fresh CPU/native preflight with zero credit.",
        },
        {
            "id": "SECOND_ROOT_REVIEW_REQUIRED",
            "status": "blocking",
            "evidence": "The existing v1 root receipt only covered the v1 input and its one preflight; the anchor review is exhausted by the retained hard failure.",
            "required": "A second root review must be separate from the CPU/native approval before any solver decision.",
        },
        {
            "id": "CORE_GATE_UNCHANGED",
            "status": "informational_blocker",
            "evidence": "Core completion still has only F3/F4 and 288 missing T1 case-runs.",
            "required": "Even a future candidate pass cannot bypass the fixed Core evaluator and production denominator.",
        },
    ]

    return {
        "schema": "core.f2.pour_catch.root_review_gap_audit.v1",
        "status": "blocked_before_new_definition",
        "candidate_id": candidate["candidate_id"],
        "decision": "hold_new_definition_until_root_gaps_are_closed",
        "worth_new_definition": True,
        "worth_preflight_now": False,
        "interpretation": (
            "The route is worth preserving as a conditional fresh hypothesis because its fixed "
            "receiver/free-fall topology is executable in principle and differs from submerged-slot; "
            "the current evidence is insufficient to write or preflight v2."
        ),
        "gaps": gaps,
        "v1_failure_preservation": {
            "loader_attempt": {
                "returncode": first_attempt["returncode"],
                "frame_count": first_attempt["frame_inventory"]["frame_count"],
                "credit": first_attempt["matrix_credit"],
            },
            "repair_attempt": {
                "frames": postrun["frame_inventory"]["count"],
                "excluded_particles": postrun["run_out_summary"]["excluded_particles"],
                "excluded_particles_density": postrun["run_out_summary"]["excluded_particles_density"],
                "hard_integrity_pass": postrun["hard_integrity_pass"],
                "credit": postrun["matrix_credit"],
            },
            "same_input_retry_allowed": False,
            "survivor_renormalization": False,
            "parent_matrix_denominator_changed": False,
        },
        "authorization": {
            "definition_writer": False,
            "cpu_gencase": False,
            "native_decode": False,
            "solver": False,
            "gpu": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
            "qualification_credit": 0,
        },
        "hash_bindings": {
            "candidate": ref(
                "campaigns/core-v1/cfd/f2-pour-catch-candidate-card-v2.json",
                "fresh route candidate card",
            ),
            "v1_root_review": ref(
                "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-v1/root-review-receipt-v1.json",
                "v1 CPU root review; not reusable for v2",
            ),
            "v1_infrastructure_retry_review": ref(
                "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-v1/solver-anchor-v1/infra-retry-root-review-v1.json",
                "v1 retry record; scientific identity unchanged",
            ),
            "v1_negative_postrun": ref(
                "campaigns/core-v1/runtime/attempts/"
                "f2-static-receiver-ballistic-catch-q05-anchor-infra-retry-v1/"
                "20260921T111854-b642c199de99/product/postrun-audit.json",
                "v1 retained hard negative",
            ),
        },
    }


def build_route(candidate: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    completion = load(local("campaigns/core-v1/completion.json"))
    registry = load(local("campaigns/core-v1/registry.json"))
    submerged = load(local("campaigns/core-v1/evidence/f2-distributed-slot-normal-repair-v2-negative-evidence.json"))
    dynamic = load(local("campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-anchor-canary-negative-evidence-v1.json"))
    weir = load(local("campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/terminal-failure-denominator-v1.json"))
    f6_report = ref(
        "reports/F6-PHYSICAL-ANCHOR-OBSERVATION-AXIS-V10-SOLVER-CANARY-V4-2026-09-21.zh-CN.md",
        "F6 v4 canary context: 7/8 with cell-08 scientific hard failure",
    )

    assert completion["t1_families"] == ["F3", "F4"]
    assert completion["checks"]["three_t1_families"] is False
    assert completion["missing_t1_case_runs"] == 288
    assert submerged["route_decision"]["normal_hypotheses_exhausted"] is True
    assert submerged["route_decision"]["same_input_retry"] is False
    assert dynamic["status"] == "completed_scientific_canary_event_censored"
    assert dynamic["matrix_credit"]["credit"] == 0
    assert weir["planned"] == 15 and weir["executed"] == 1
    assert weir["failed"] == 1 and weir["event_censored"] == 1

    return {
        "schema": "core.f2.pour_catch.route_decision.v1",
        "status": "root_review_only_conditional_route",
        "trigger": "F6 v4 canary aggregate is 7/8; cell-08 is retained as a scientific hard failure",
        "core_gate": {
            "registered_t1_families": completion["t1_families"],
            "required_t1_family_count": 3,
            "three_t1_families": completion["checks"]["three_t1_families"],
            "missing_t1_case_runs": completion["missing_t1_case_runs"],
            "registry_contains_f2_scope": any(
                item.get("family") == "F2" for item in registry.get("scope_studies", [])
            ),
            "qualification_credit_added": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
        },
        "route_comparison": {
            "closed_submerged_slot": {
                "status": "closed_negative",
                "zero_boundnor": submerged["preflight"]["native_initial"]["zero_boundnor_count"],
                "zero_normalsize": submerged["preflight"]["native_initial"]["normal_size_zero_count"],
                "same_input_retry": submerged["route_decision"]["same_input_retry"],
                "credit": submerged["matrix_credit"],
            },
            "closed_dynamic_dbc": {
                "status": "closed_event_censored",
                "hard_integrity_pass": dynamic["scientific_result"]["hard_integrity_pass"],
                "event_window_complete": dynamic["scientific_result"]["event_window_complete"],
                "same_input_retry": dynamic["classification"]["same_input_retry_allowed"],
                "credit": dynamic["matrix_credit"]["credit"],
            },
            "closed_receiver_weir": {
                "status": "closed_terminal_anchor_negative",
                "planned": weir["planned"],
                "executed": weir["executed"],
                "failed": weir["failed"],
                "event_censored": weir["event_censored"],
                "unattempted": weir["unattempted"],
                "credit": weir["credit"],
                "same_input_retry": weir["preservation"]["same_input_retry"],
            },
            "selected_receiver_ballistic_v2": {
                "status": candidate["status"],
                "candidate_id": candidate["candidate_id"],
                "scope_id": candidate["scope_id"],
                "mechanism_class": candidate["mechanism_class"],
                "distinct_from_closed_submerged_slot": candidate["topology"]["distinct_from_closed_route"],
                "worth_new_definition": gap["worth_new_definition"],
                "worth_preflight_now": gap["worth_preflight_now"],
            },
        },
        "selected_route": {
            "decision": "retain_conditional_f2_stationary_receiver_ballistic_catch_v2",
            "reason": [
                "The fixed receiver plus falling slug has no submerged aperture, crest, or moving cup.",
                "Legacy airborne-slug evidence supports only plumbing/ballistic feasibility and is not imported as qualification evidence.",
                "The v1 anchor failures are retained and make same-input retry forbidden.",
                "A lower release-speed v2 is a falsifiable fresh hypothesis with a new identity, not a relabelled v1 retry.",
            ],
            "next_action": "root-review-only gap closure; do not write Definition or run preflight in this audit",
            "qualification_claim": "none",
            "matrix_credit": 0,
            "old_failed_input_reused": False,
            "old_failed_trajectory_reused": False,
            "same_input_retry": False,
        },
        "root_review_gap_audit": {
            "path": "campaigns/core-v1/cfd/f2-pour-catch-root-review-gap-audit-v1.json",
            "sha256": sha256(GAP_OUTPUT),
            "bytes": GAP_OUTPUT.stat().st_size,
        },
        "candidate_card": {
            "path": "campaigns/core-v1/cfd/f2-pour-catch-candidate-card-v2.json",
            "sha256": sha256(CANDIDATE_OUTPUT),
            "bytes": CANDIDATE_OUTPUT.stat().st_size,
        },
        "evidence": {
            "completion": ref("campaigns/core-v1/completion.json", "current Core gate"),
            "registry": ref("campaigns/core-v1/registry.json", "unchanged Core registry"),
            "closed_submerged_slot": ref(
                "campaigns/core-v1/evidence/f2-distributed-slot-normal-repair-v2-negative-evidence.json",
                "closed submerged-slot negative evidence",
            ),
            "closed_dynamic_dbc": ref(
                "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-anchor-canary-negative-evidence-v1.json",
                "closed DBC event-censored evidence",
            ),
            "closed_receiver_weir_denominator": ref(
                "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1/terminal-failure-denominator-v1.json",
                "receiver/weir failure denominator",
            ),
            "f6_context": f6_report,
            "implementation": ref(
                "scripts/f2_pour_catch_route_audit_v1.py",
                "read-only route audit implementation",
            ),
            "test": ref(
                "tests/test_f2_pour_catch_route_audit_v1.py",
                "targeted route audit regression test",
            ),
        },
        "execution_controls": {
            "read_only_audit": True,
            "definition_writer": False,
            "cpu_gencase": False,
            "native_decode": False,
            "solver": False,
            "gpu": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
        },
    }


def render_report(route: dict[str, Any], candidate: dict[str, Any], gap: dict[str, Any]) -> str:
    v1 = candidate["retained_v1_negative"]
    return "\n".join(
        [
            "# F2 倾倒/接液替补路线只读审计（2026-09-21）",
            "",
            "F6 v4 的 8 格 canary 为 7/8，cell-08 保留科学硬失败；本审计只读复核现有 F2 资格、registry 和报告，未启动任何 GenCase、native decoder、solver、GPU 或 queue。",
            "",
            "结论是保留一条新的固定接收盆+自由落体液块路线作为有条件候选：`F2_receiver_ballistic_catch_release010_v2`。它没有 submerged aperture、crest 或 moving cup，与已关闭的 submerged-slot 负例在拓扑上独立。候选只停留在 root-review-only；当前不写 Definition、不做 preflight。",
            "",
            "## 失败证据与分母",
            "",
            f"- submerged-slot v2 已有 `{route['route_comparison']['closed_submerged_slot']['zero_boundnor']}` 个 zero BoundNor/NormalSize，route 明确关闭且禁止同输入 retry；保留 `matrix_credit=0`。",
            f"- receiver/weir 的固定 15 行保留 `executed={route['route_comparison']['closed_receiver_weir']['executed']}`、`failed={route['route_comparison']['closed_receiver_weir']['failed']}`、`event_censored={route['route_comparison']['closed_receiver_weir']['event_censored']}`、`unattempted={route['route_comparison']['closed_receiver_weir']['unattempted']}`，不重跑。",
            f"- 静态接收盆 v1 q=.5 anchor 的第一次 loader attempt 返回 127；随后唯一允许的基础设施修复重试完成 301 帧，但排除 `{v1['repair_attempt_excluded_particles']}` 个粒子（其中 density 排除 `{v1['repair_attempt_excluded_particles_density']}`），所以 hard integrity=false。两次失败均保留，v1 输入、XML/BI4、trajectory 和 output stem 均关闭。",
            "- v2 仅提出新的 `-0.10 m/s` release-speed 假设；建议的 15 行仍是 proposal-only，`executed=0`、`credit=0`，不改已有 T1/T2 分母。",
            "",
            "## Root-review gap",
            "",
            "当前阻塞项是：没有 v2 literal Definition/hash closure；v1 CPU/native pass 不能继承；v1 科学硬失败禁止 same-input retry；receiver contact、retained/spill ownership 和 q endpoint observer 尚未 root 冻结；还需要一次新的 root review，再考虑恰好一次 v2 CPU/native preflight。",
            "",
            "是否值得进入新 Definition/preflight：**条件性值得保留，但当前不值得执行 preflight**。固定 receiver/free-fall 机制有独立问题和有限的历史 ballistic/plumbing 依据；只有先补齐上述 root-review gap，且新 Definition 明确改变 release-speed、case identity 和 output namespace 后，才进入一次零 credit CPU/native preflight。",
            "",
            "## Gate 与执行控制",
            "",
            f"Core 仍为 `t1_families={route['core_gate']['registered_t1_families']}`、`missing_t1_case_runs={route['core_gate']['missing_t1_case_runs']}`、`qualification_credit_added=0`。本次 `registry_mutation=0`、`ledger_mutation=0`、`T1_denominator_mutation=0`、`T2_denominator_mutation=0`；没有 solver/GPU/queue。",
            "",
            "定向回归：`pytest -q tests/test_f2_pour_catch_route_audit_v1.py`。",
            "",
        ]
    )


def write_outputs() -> dict[str, Any]:
    candidate = build_candidate()
    CANDIDATE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATE_OUTPUT.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    gap = build_gap(candidate)
    GAP_OUTPUT.write_text(json.dumps(gap, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    route = build_route(candidate, gap)
    ROUTE_OUTPUT.write_text(json.dumps(route, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    REPORT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUTPUT.write_text(render_report(route, candidate, gap), encoding="utf-8")
    return route


def verify(path: Path = ROUTE_OUTPUT) -> dict[str, Any]:
    route = load(path)
    if route["schema"] != "core.f2.pour_catch.route_decision.v1":
        raise AssertionError("wrong route schema")
    if route["status"] != "root_review_only_conditional_route":
        raise AssertionError("route is not proposal-only")
    if route["core_gate"]["qualification_credit_added"] != 0:
        raise AssertionError("unexpected qualification credit")
    controls = route["execution_controls"]
    for key in ("definition_writer", "cpu_gencase", "native_decode", "solver", "gpu"):
        if controls[key] is not False:
            raise AssertionError(f"execution opened: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "T1_denominator_mutation", "T2_denominator_mutation"):
        if controls[key] != 0:
            raise AssertionError(f"mutation opened: {key}")
    for item in route["evidence"].values():
        target = local(item["path"])
        if target.stat().st_size != item["bytes"] or sha256(target) != item["sha256"]:
            raise AssertionError(f"stale evidence binding: {item['path']}")
    candidate = load(CANDIDATE_OUTPUT)
    if candidate["fresh_input_contract"]["same_input_retry"] is not False:
        raise AssertionError("same-input retry was enabled")
    if candidate["fresh_input_contract"]["v1_generated_bi4_reused"] is not False:
        raise AssertionError("v1 BI4 reuse was enabled")
    if candidate["planned_matrix"]["credit"] != 0:
        raise AssertionError("candidate has matrix credit")
    return route


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write", "verify"), nargs="?", default="write")
    args = parser.parse_args()
    if args.command == "write":
        result = write_outputs()
        print(json.dumps({"written": str(ROUTE_OUTPUT), "candidate": str(CANDIDATE_OUTPUT), "gap": str(GAP_OUTPUT)}, ensure_ascii=False, indent=2))
    else:
        verify()
        print(json.dumps({"verified": True, "path": str(ROUTE_OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
