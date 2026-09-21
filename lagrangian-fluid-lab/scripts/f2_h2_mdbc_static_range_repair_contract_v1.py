#!/usr/bin/env python3
"""Audit and bind the H2 static-range mass repair evidence.

This is a read-only contract builder.  It compares the retained v4 cell-11
failure with the already materialized v5 CPU/native closure.  It does not
run GenCase, decode BI4, launch a solver, allocate a GPU, submit a queue job,
or mutate the ledger/registry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / (
    "campaigns/core-v1/cfd/"
    "f2-h2-mdbc-static-range-repair-preflight-contract-20260921.json"
)
REPORT = LAB / "reports/F2-H2-MDBC-STATIC-RANGE-REPAIR-2026-09-21.zh-CN.md"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(LAB))


def bind(path: Path, role: str) -> dict[str, Any]:
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
    baseline_matrix_path = _p(
        "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v1/"
        "prepared-20260920-v4/matrix-preparation.json"
    )
    baseline_cell11_path = _p(
        "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v1/"
        "prepared-20260920-v4/cells/"
        "11-CORE_F2_H2_mdbc_static_range_q0p75000000_dp0p007500000000_"
        "spatial_held_out/preflight.json"
    )
    candidate_path = _p(
        "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-"
        "candidate-v5.json"
    )
    plan_path = _p(
        "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
        "v5-plan-20260920-final.json"
    )
    matrix_path = _p(
        "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
        "prepared-20260920-v5-all/matrix-preparation.json"
    )
    cell11_preflight_path = _p(
        "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
        "prepared-20260920-v5-all/cells/"
        "11-CORE_F2_H2_mdbc_static_range_v5_q0p75000000_dp0p007500000000_"
        "spatial_held_out/preflight.json"
    )
    cell11_prepared_path = _p(
        "campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/"
        "prepared-20260920-v5-all/cells/"
        "11-CORE_F2_H2_mdbc_static_range_v5_q0p75000000_dp0p007500000000_"
        "spatial_held_out/prepared.json"
    )
    implementation_path = _p("scripts/f2_h2_mdbc_static_range_v5_prepare.py")
    prior_test_path = _p("tests/test_f2_h2_mdbc_static_range_v5_prepare.py")

    baseline_matrix = load(baseline_matrix_path)
    baseline_cell11 = load(baseline_cell11_path)
    candidate = load(candidate_path)
    plan = load(plan_path)
    matrix = load(matrix_path)
    cell11 = load(cell11_preflight_path)
    cell11_prepared = load(cell11_prepared_path)

    baseline_rows = baseline_matrix["failure_denominator"]["rows"]
    v5_rows = matrix["cells"]
    old_source_errors = baseline_cell11["mass_gate"]["source_relative_errors"]
    new_source_errors = cell11["mass_gate"]["source_relative_errors"]
    hypothesis = matrix["discrete_sampling_hypothesis"]

    assert baseline_matrix["registered_cell_count"] == 15
    assert baseline_matrix["prepared_cell_count"] == 14
    assert baseline_matrix["failed_cell_count"] == 1
    assert baseline_matrix["unattempted_cell_count"] == 0
    assert baseline_rows[11]["status"] == "failed"
    assert baseline_cell11["preflight_pass"] is False
    assert old_source_errors[2] == 0.02806106870228997
    assert old_source_errors[2] > 0.025
    assert baseline_cell11["mass_rescaling"] is False

    assert candidate["qualified"] is False
    assert candidate["T1_numerical"] is False
    assert candidate["qualification_only"] is True
    assert candidate["central_ledger_mutation"] == 0
    assert candidate["registry_mutation"] == 0
    assert matrix["registered_cell_count"] == 15
    assert matrix["status"] == "prepared_cpu_only"
    assert matrix["prepared_cell_count"] == 15
    assert matrix["failed_cell_count"] == 0
    assert matrix["unattempted_cell_count"] == 0
    assert matrix["qualification_claim"].startswith("none;")
    assert len(v5_rows) == 15
    assert all(row["preflight_pass"] is True for row in v5_rows)
    assert all(row["qualification_credit"] is False for row in v5_rows)
    assert matrix["execution_controls"]["solver_invoked"] is False
    assert matrix["execution_controls"]["gpu_invoked"] is False
    assert matrix["execution_controls"]["queue_mutation"] == 0
    assert matrix["execution_controls"]["ledger_mutation"] == 0
    assert matrix["execution_controls"]["registry_mutation"] == 0
    assert matrix["execution_controls"]["qualification_claim_allowed"] is False
    assert cell11["preflight_pass"] is True
    assert new_source_errors[2] == 0.004152671755724757
    assert new_source_errors[2] < 0.025
    assert cell11["mass_gate"]["mass_rescaling"] is False
    assert cell11["mass_gate"]["total_discrete_to_continuum_mass_error_max"] == 0.03
    assert cell11["checks"]["source_initial_mass_gate"] is True
    assert cell11["checks"]["decoded_native_mass_gate"] is True
    assert cell11_prepared["solver_invoked"] is False
    assert cell11_prepared["gpu_invoked"] is False
    assert cell11_prepared["queue_mutated"] is False
    assert cell11_prepared["ledger_mutated"] is False
    assert cell11_prepared["registry_mutated"] is False
    assert hypothesis["hypothesis_id"] == "H2_v5_top_layer_lateral_lattice_balance"
    assert hypothesis["cell_11_old_third_source_error"] > 0.025
    assert hypothesis["cell_11_new_third_source_error"] < 0.025
    assert hypothesis["threshold_selection"].find("0.025") >= 0

    evidence = {
        "baseline_v4_matrix": bind(baseline_matrix_path, "retained v4 15-cell denominator"),
        "baseline_v4_cell11": bind(baseline_cell11_path, "retained v4 cell-11 negative preflight"),
        "v5_candidate": bind(candidate_path, "H2 v5 repair candidate proposal"),
        "v5_plan": bind(plan_path, "H2 v5 CPU/native preparation plan"),
        "v5_matrix": bind(matrix_path, "H2 v5 full-scope CPU/native preflight"),
        "v5_cell11_preflight": bind(cell11_preflight_path, "H2 v5 repaired cell-11 preflight"),
        "v5_cell11_prepared": bind(cell11_prepared_path, "H2 v5 repaired cell-11 prepared input"),
        "v5_implementation": bind(implementation_path, "H2 v5 materializer implementation"),
        "prior_test": bind(prior_test_path, "H2 v5 materializer regression test"),
    }

    return {
        "schema": "core.f2.h2_mdbc.static_range.repair_preflight_contract.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed_cpu_native_repair_evidence_zero_credit",
        "family": "F2",
        "scope_id": "F2_H2_mdbc_static_range_qualification_v5",
        "parent_scope_id": "F2_H2_mdbc_static_range_qualification_v1",
        "candidate_id": candidate["candidate_id"],
        "qualification_claim": "none; CPU/native repair evidence only",
        "qualified": False,
        "T1_numerical": False,
        "hypothesis_policy": {
            "maximum_hypothesis_classes": 2,
            "selected_hypothesis_classes": 1,
            "second_class": "not_needed_after_v5_full_scope_preflight_pass",
            "reason": "The single evidence-backed top-layer lattice change resolves the retained cell-11 mass gate across the full 15-cell CPU/native closure; adding an untested second class would add no evidence and is deferred.",
        },
        "proposal": {
            "status": "hash_bound_candidate_proposal_with_historical_cpu_native_closure",
            "candidate": evidence["v5_candidate"],
            "new_input_identity": True,
            "old_v4_input_reused": False,
            "output_stem": matrix["matrix_output"],
            "full_scope_materialized": True,
            "runtime_authorized": False,
            "solver_gpu_queue_authorized": False,
            "qualification_claim_allowed": False,
            "qualification_credit": 0,
        },
        "retained_failure": {
            "matrix_cell_count": baseline_matrix["registered_cell_count"],
            "prepared_cell_count": baseline_matrix["prepared_cell_count"],
            "failed_cell_count": baseline_matrix["failed_cell_count"],
            "failed_index": 11,
            "case_id": baseline_cell11["case_id"],
            "q": baseline_cell11["q"],
            "dp_m": baseline_cell11["dp_m"],
            "source_relative_errors": old_source_errors,
            "failing_third_layer_error": old_source_errors[2],
            "source_gate": 0.025,
            "total_gate": 0.03,
            "mass_rescaling": False,
            "same_input_retry": False,
            "failure_remains_in_denominator": True,
            "evidence": evidence["baseline_v4_cell11"],
        },
        "repair_hypotheses": [
            {
                "hypothesis_id": hypothesis["hypothesis_id"],
                "class": "top_layer_lateral_integer_lattice_balance",
                "status": "supported_and_cpu_native_verified",
                "independent_input_identity": True,
                "same_input_retry": False,
                "changed_counts": {
                    "old_layer_counts": hypothesis["cell_11_old_counts"],
                    "new_layer_counts": hypothesis["cell_11_new_counts"],
                },
                "old_third_layer_error": hypothesis["cell_11_old_third_source_error"],
                "predicted_third_layer_error": hypothesis["cell_11_new_third_source_error"],
                "predicted_total_error": hypothesis["cell_11_new_total_error"],
                "observed_third_layer_error": new_source_errors[2],
                "observed_total_error": cell11["mass_gate"]["mass_error_relative"],
                "selection_rule": hypothesis["candidate_axis_rule"],
                "center_rule": hypothesis["center_rule"],
                "threshold_rule": "source relative mass error <= 0.025 and total discrete-to-continuum error <= 0.03; thresholds are fixed and excluded from optimization",
                "mass_policy": "native rho*dp^3; no mass rescaling",
                "falsifier": hypothesis["falsifier"],
            }
        ],
        "cpu_native_preflight_contract": {
            "mode": "CPU GenCase plus native BI4 decode only",
            "input_output_stem": matrix["matrix_output"],
            "full_scope_rows": 15,
            "full_scope_preflight_passed": 15,
            "full_scope_failed": 0,
            "full_scope_unattempted": 0,
            "cell_11": {
                "index": 11,
                "case_id": cell11["case_id"],
                "preflight_pass": cell11["preflight_pass"],
                "source_relative_errors": new_source_errors,
                "source_gate": cell11["mass_gate"]["source_initial_mass_relative_error_max"],
                "total_error": cell11["mass_gate"]["mass_error_relative"],
                "total_gate": cell11["mass_gate"]["total_discrete_to_continuum_mass_error_max"],
                "mass_rescaling": cell11["mass_gate"]["mass_rescaling"],
                "normal_count": cell11["native_identity"]["boundary_particles"],
                "zero_normal_gate": cell11["checks"]["mdbc_zero_boundary_normals_gate"],
            },
            "qualification_credit": 0,
            "solver_product_present": False,
            "future_runtime_authorization": False,
        },
        "failure_denominator": {
            "planned": 15,
            "cpu_native_preflight_passed": 15,
            "qualification_numerator": 0,
            "failed_rows_dropped": False,
            "parent_v4_failure_retained": True,
            "survivor_renormalization": False,
            "threshold_relaxation": False,
            "same_input_retry": False,
        },
        "execution_controls": {
            "this_contract_runs_gencase": False,
            "this_contract_runs_decoder": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_credit": 0,
        },
        "core_gate_effect": {
            "current_registered_t1_families": ["F3", "F4"],
            "third_t1_family_established": False,
            "qualification_credit_added": 0,
            "core_gate_changed": False,
        },
        "hash_bindings": evidence,
        "required_next_review": "independent root review of the completed v5 CPU/native closure before any solver or T1 consideration",
        "interpretation_boundary": "This contract proves only a fresh CPU/native mass/identity/normal input closure. It does not prove static event, runtime integrity, range qualification, or T1 registration.",
    }


def render_report(contract: dict[str, Any]) -> str:
    h = contract["repair_hypotheses"][0]
    pre = contract["cpu_native_preflight_contract"]
    retained = contract["retained_failure"]
    return "\n".join(
        [
            "# F2 H2 mDBC static-range 离散化修复审计（2026-09-21）",
            "",
            "现有 v4 H2 static-range 15-cell CPU/native 预检为 14/15 通过；固定 held-out cell 11（q=0.75，dp=0.0075）因第三源层相对质量误差 `0.02806106870228997 > 0.025` 失败。该失败保留在原始 15 行分母中，没有重跑同一输入，也没有删除失败行。",
            "",
            f"本次只采用一类有证据的修复假设：`{h['hypothesis_id']}`。它保持两个较低源层和连续几何不变，只对第三源层选择居中的整数横向格点计数；cell 11 由旧 `[43,29,16]` 调整为新 `[42,29,16]`，第三层误差由 `{h['old_third_layer_error']}` 降至实测 `{h['observed_third_layer_error']}`，总离散质量误差为 `{h['observed_total_error']}`。质量门仍固定为 source `0.025`、total `0.03`，不进入优化，也不做质量重标定。",
            "",
            f"已有 v5 full-scope CPU/native 证据显示 15/15 行通过，cell 11 的 normal/identity/finite/mass checks 均通过；这只是输入闭合，资格 credit 仍为 0，solver product 不存在。由于单一假设已在 full scope 预检中通过，本合同不增加第二个未经验证的修复类别。",
            "",
            "## 固定边界",
            "",
            f"- 保留失败：v4 `prepared={retained['matrix_cell_count'] - retained['failed_cell_count']}`、`failed={retained['failed_cell_count']}`；cell 11 source errors={retained['source_relative_errors']}。",
            f"- 新输入：v5 output stem `{pre['input_output_stem']}`，15/15 CPU/native pass，`qualification_credit=0`。",
            "- native mass policy 为 `rho*dp^3`，不允许质量重标定；未知/失败行仍保留，不能 survivor renormalization。",
            "- 本轮脚本只读取和绑定既有证据，不运行 GenCase/decoder，不启动 solver/GPU/queue，不写 ledger/registry。",
            "",
            "## 资格边界和下一步",
            "",
            "v5 仍是 qualification-only CPU/native closure，不能替代静态事件、runtime hard-integrity 或 15-cell T1 evaluator。下一步只能由独立 root review 审查该闭合后再决定是否生成新的 runtime proposal；本合同不授权任何 runtime。",
            "",
            "## 产物",
            "",
            "- contract：`campaigns/core-v1/cfd/f2-h2-mdbc-static-range-repair-preflight-contract-20260921.json`。",
            f"- implementation：`{contract['hash_bindings']['v5_implementation']['path']}`，SHA `{contract['hash_bindings']['v5_implementation']['sha256']}`。",
            "- contract 的 `hash_bindings` 固定绑定 v4 failed matrix/cell、v5 candidate/plan/full matrix/cell 11 preflight/prepared、materializer 和回归测试。",
            "",
            "Core gate 未改变：third T1 family 未建立，qualification credit=0，registry/ledger mutation=0。",
            "",
        ]
    )


def write_outputs(output: Path = OUTPUT, report: Path = REPORT) -> dict[str, Any]:
    contract = build_contract()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(contract), encoding="utf-8")
    return contract


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    if value["schema"] != "core.f2.h2_mdbc.static_range.repair_preflight_contract.v1":
        raise AssertionError("wrong schema")
    if value["core_gate_effect"]["core_gate_changed"] is not False:
        raise AssertionError("Core gate changed")
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
