#!/usr/bin/env python3
"""Audit the W08/W10 split-lineage contract without running a solver.

The first W08 implementation audited unique execution signatures but assigned
one ``lineage_group_id`` to an entire family.  That is a useful regression
fixture: the W08 signature-only audit accepts it while the W10 lineage gate
correctly rejects it because the same lineage spans several splits.

The repository's current W08 generator has already been repaired.  This
script keeps the historical reproduction in an isolated, candidate-only
diagnostic rather than changing either the W08 or W10 production primitive.
It is intentionally CPU-only and only constructs small Python dictionaries.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

try:  # package import under pytest and execution from the lab root
    from scripts.protocol_metrics import validate_split_lineage
    from scripts.w08_generalization_design import audit as w08_audit
    from scripts.w08_generalization_design import build_cards
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from protocol_metrics import validate_split_lineage
    from w08_generalization_design import audit as w08_audit
    from w08_generalization_design import build_cards


LAB = Path(__file__).resolve().parents[1]
W08_DESIGN = LAB / "campaigns" / "v0.1-candidate" / "cases" / "w08" / "controlled-generalization-design.json"


def _split_map(records: Iterable[dict[str, Any]], key: str) -> dict[str, list[str]]:
    values: dict[str, set[str]] = defaultdict(set)
    for record in records:
        values[str(record[key])].add(str(record["split"]))
    return {name: sorted(splits) for name, splits in sorted(values.items())}


def historical_w08_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project current physics cards onto the pre-918 W08 identity contract.

    Before the lineage fix, W08 used ``W08_<family>_controlled`` for every
    card in a family and did not carry ``physical_case_id`` or a paired
    background field.  Keeping the current card physics and execution IDs
    makes this a focused identity regression, rather than a second design.
    """

    projected: list[dict[str, Any]] = []
    for card in cards:
        legacy = copy.deepcopy(card)
        legacy.pop("physical_case_id", None)
        legacy.pop("paired_background_id", None)
        legacy["lineage_group_id"] = f"W08_{card['family']}_controlled"
        projected.append(legacy)
    return projected


def signature_only_w08_audit(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Reproduce the old W08 audit that did not call the W10 primitive."""

    if len(cards) != 204:
        raise AssertionError(f"expected 204 cards, got {len(cards)}")
    if len({card["card_id"] for card in cards}) != len(cards):
        raise AssertionError("card IDs are not unique")
    split_by_execution: dict[str, set[str]] = defaultdict(set)
    for card in cards:
        split_by_execution[card["execution_unit_id"]].add(card["split"])
    leakage = {
        key: sorted(splits)
        for key, splits in sorted(split_by_execution.items())
        if len(splits) > 1
    }
    if leakage:
        raise AssertionError(f"identical physical states cross splits: {leakage}")
    return {
        "cards": len(cards),
        "unique_execution_units": len(split_by_execution),
        "cross_split_signature_leakage": leakage,
        "lineage_gate_called": False,
        "status": "pass",
    }


def _validate_result(records: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        validate_split_lineage(records)
    except (ValueError, AssertionError) as exc:
        return {
            "status": "reject",
            "exception_type": type(exc).__name__,
            "reason": str(exc),
        }
    return {"status": "accept"}


def candidate_w08_contract(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply a stricter W08-card adapter as a candidate-only proposal.

    W10 release records intentionally make ``physical_case_id`` optional for
    older records, so tightening the global W10 function would change legacy
    semantics.  This adapter scopes the additional checks to W08 design cards:
    all four identity keys are present, and one physical state has exactly one
    lineage and execution unit.  It is diagnostic code, not a release gate.
    """

    required = (
        "card_id",
        "family",
        "study_id",
        "paired_background_id",
        "physical_case_id",
        "lineage_group_id",
        "split",
        "simulation_signature",
        "execution_unit_id",
    )
    missing = {
        card.get("card_id", f"record-{index}"): [key for key in required if not card.get(key)]
        for index, card in enumerate(cards)
    }
    missing = {card_id: keys for card_id, keys in missing.items() if keys}
    if missing:
        raise ValueError(f"W08 identity fields missing: {missing}")

    # Reuse the actual W10 primitive first, then add W08's cross-namespace
    # consistency checks.  Paired backgrounds are deliberately not checked as
    # split keys: their intentional cross-split reuse is part of the protocol.
    validate_split_lineage(cards)
    physical_to_lineage: dict[str, set[str]] = defaultdict(set)
    physical_to_execution: dict[str, set[str]] = defaultdict(set)
    execution_to_physical: dict[str, set[str]] = defaultdict(set)
    for card in cards:
        physical = card["physical_case_id"]
        physical_to_lineage[physical].add(card["lineage_group_id"])
        physical_to_execution[physical].add(card["execution_unit_id"])
        execution_to_physical[card["execution_unit_id"]].add(physical)

    bad_lineage = {
        key: sorted(value) for key, value in physical_to_lineage.items() if len(value) != 1
    }
    bad_execution = {
        key: sorted(value) for key, value in physical_to_execution.items() if len(value) != 1
    }
    bad_reverse = {
        key: sorted(value) for key, value in execution_to_physical.items() if len(value) != 1
    }
    if bad_lineage or bad_execution or bad_reverse:
        raise ValueError(
            "W08 identity mappings are not one-to-one: "
            f"physical_to_lineage={bad_lineage}, "
            f"physical_to_execution={bad_execution}, "
            f"execution_to_physical={bad_reverse}"
        )
    return {
        "status": "pass",
        "scope": "W08 design cards only",
        "required_identity_fields": list(required),
        "physical_case_count": len(physical_to_lineage),
        "lineage_count": len({card["lineage_group_id"] for card in cards}),
        "execution_unit_count": len(execution_to_physical),
        "paired_background_is_not_a_split_key": True,
    }


def run_diagnostic() -> dict[str, Any]:
    """Return a deterministic report for the current tree and regression."""

    cards = build_cards()
    current_audit = w08_audit(cards)
    current_validation = _validate_result(cards)
    current_candidate = candidate_w08_contract(cards)

    persisted = json.loads(W08_DESIGN.read_text())
    persisted_cards = persisted["cards"]
    historical = historical_w08_cards(cards)
    historical_audit = signature_only_w08_audit(historical)
    historical_validation = _validate_result(historical)
    historical_lineages = _split_map(historical, "lineage_group_id")
    historical_cross_split = {
        key: splits for key, splits in historical_lineages.items() if len(splits) > 1
    }

    return {
        "schema_version": 1,
        "status": "candidate-only",
        "cpu_only": True,
        "solver_invoked": False,
        "source_refs": {
            "w08_design_script": "scripts/w08_generalization_design.py",
            "w10_validator": "scripts/protocol_metrics.py::validate_split_lineage",
            "w10_adversarial_script": "scripts/w10_protocol_audit.py",
            "current_w08_design": str(W08_DESIGN.relative_to(LAB)),
            "historical_fix_boundary": "91847d6 (W08 lineage audit) / 72c353f (W08-W10 physical-case alignment)",
        },
        "current_tree": {
            "card_count": len(cards),
            "w08_audit": {"status": "pass", "result": current_audit},
            "w10_validate_split_lineage": current_validation,
            "candidate_w08_contract": current_candidate,
            "persisted_card_count": len(persisted_cards),
            "persisted_matches_generator": persisted_cards == cards,
        },
        "historical_reproduction": {
            "status": "reproduced",
            "fixture": "pre-918 W08 identity projection over current 204 physics cards",
            "card_count": len(historical),
            "w08_signature_only_audit": historical_audit,
            "w10_validate_split_lineage": historical_validation,
            "cross_split_lineages": historical_cross_split,
            "interpretation": (
                "The old W08 audit accepted unique execution signatures, while W10 "
                "rejected the family-shared lineage_group_id across train/interpolation/"
                "extrapolation splits."
            ),
        },
        "diagnosis": {
            "root_cause": "W08 and W10 used different split keys: execution signature versus lineage_group_id.",
            "current_status": "fixed in the current tree; no current-card rejection was observed",
            "remaining_contract_risk": (
                "The global W10 validator permits records without physical_case_id for legacy compatibility, "
                "so W08-specific identity completeness and one-to-one mapping need an explicit adapter or schema gate."
            ),
        },
        "candidate_contract_fix": {
            "status": "candidate-only",
            "applied_to_existing_sources": False,
            "proposal": "Run the W10 lineage primitive plus W08 identity-completeness and mapping checks before materialization.",
            "rules": [
                "Require physical_case_id, lineage_group_id, execution_unit_id, and split on every W08 card.",
                "Require one physical_case_id to map to one split, one lineage_group_id, and one execution_unit_id.",
                "Require one execution_unit_id to map to one physical_case_id and one split.",
                "Allow paired_background_id to repeat across intervention splits; it is not a split key.",
            ],
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    historical = report["historical_reproduction"]
    current = report["current_tree"]
    return f"""# R3 G1 lineage contract diagnostic

状态：**candidate-only 诊断，不是正式验收**。本检查只构造 Python records；不调用 GenCase、DualSPHysics 或 GPU。

## 结论

当前 HEAD 的 W08 generator 生成 {current['card_count']} 张卡片，W08 `audit()` 通过，W10 `validate_split_lineage()` 也通过；持久化设计文件与 generator 输出一致：`{current['persisted_matches_generator']}`。因此当前树中没有再观察到旧的拒绝。

审阅者指出的历史不一致可稳定复现：把当前 204 张物理卡投影到 pre-918 W08 的 family-shared `lineage_group_id` 后，旧的 W08 signature-only audit 仍通过，而 W10 validator 拒绝：

- W08 signature-only audit：`{historical['w08_signature_only_audit']['status']}`，196 个 execution units，无跨 split signature leakage。
- W10 `validate_split_lineage`：`{historical['w10_validate_split_lineage']['status']}`，原因是 family lineage 同时出现在多个 split。
- 复现中的跨 split lineage 数：`{len(historical['cross_split_lineages'])}`（F1、F2、F3、F6 各一条）。

根因是两个阶段曾使用不同的 split key：W08 只看 `execution_unit_id`，W10 看 `lineage_group_id`。当前树已经把 W08 audit 接到 W10 primitive，并将 lineage 按 exact physical case 生成；本目录保留的是回归证据，不改写既有语义。

## candidate-only contract 建议

在 W08 materialization 前运行 W10 primitive，并额外要求 W08 卡片具备完整的 `physical_case_id`、`lineage_group_id`、`execution_unit_id` 和 `split`；同一 physical case 必须唯一映射到一个 split、lineage 和 execution unit，反向 execution 映射也必须唯一。`paired_background_id` 继续允许按干预协议跨 split 复用，不作为 split key。

这套额外检查仅在新增脚本中作为候选适配器演示，**未修改** `scripts/protocol_metrics.py`、`scripts/w08_generalization_design.py`、upstream solver 或发布门禁。

## 证据入口

- `scripts/r3_g1_lineage_contract.py`
- `tests/test_r3_g1_lineage_contract.py`
- `scripts/w08_generalization_design.py`
- `scripts/protocol_metrics.py::validate_split_lineage`
- 历史修复边界：`91847d6`、`72c353f`
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    report = run_diagnostic()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(report))


if __name__ == "__main__":
    main()
