"""Tests for the read-only F3 MLP diagnostic batch rollup auditor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f3_mlp_hidden16_current_manifest_diagnostic_rollup_audit_v1 as audit


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n")


def _zero_credit() -> dict[str, object]:
    return dict(audit.ZERO_CREDIT)


def _plan(case_id: str, seed: int, index: int, *, namespace: str | None = None) -> dict[str, object]:
    return {
        "case_id": case_id,
        "seed": seed,
        "case_index": index,
        "transitions": audit.EXPECTED_TRANSITIONS,
        "frames": audit.EXPECTED_FRAMES,
        "output_namespace": namespace or f"/tmp/synthetic-f3-{case_id}-seed{seed}",
        **_zero_credit(),
    }


def _result(case_id: str, seed: int, *, blocked: bool = False, positive_credit: bool = False) -> dict[str, object]:
    if blocked:
        value: dict[str, object] = {
            "schema": audit.RUNNER_SCHEMA,
            "status": "blocked_worker_fail_closed",
            "case_id": case_id,
            "seed": seed,
            "launched": False,
            "proof_written": False,
            "error": "synthetic fail-closed",
            **_zero_credit(),
        }
    else:
        value = {
            "schema": audit.RUNNER_SCHEMA,
            "status": "exited_successfully",
            "case_id": case_id,
            "seed": seed,
            "launched": True,
            "proof_written": True,
            "proof_path": f"/tmp/synthetic-{case_id}-seed{seed}-process-proof.json",
            "transitions": audit.EXPECTED_TRANSITIONS,
            "finite_rollout_complete": True,
            "validator_passed": True,
            **_zero_credit(),
        }
    if positive_credit:
        value["credit"] = 1
    return value


def _batch_report(
    batch_id: str,
    rows: list[tuple[str, int]],
    *,
    blocked: bool = False,
    positive_credit: bool = False,
) -> dict[str, object]:
    plans = [_plan(case_id, seed, index, namespace=f"/tmp/{batch_id}-{index}") for index, (case_id, seed) in enumerate(rows)]
    results = [_result(case_id, seed, blocked=blocked, positive_credit=positive_credit) for case_id, seed in rows]
    terminal_paths = [] if blocked else [{"case_id": case_id, "seed": seed} for case_id, seed in rows]
    value: dict[str, object] = {
        "schema": audit.RUNNER_SCHEMA,
        "report_id": "f3-mlp-hidden16-current-manifest-diagnostic-batch-v1",
        "status": "blocked_diagnostic_batch" if blocked else "completed_diagnostic_batch",
        "batch_id": batch_id,
        "source_bound": True,
        "plans": plans,
        "results": results,
        "coverage": {
            "selected_case_count": len(rows),
            "terminal_receipts_required": len(rows),
            "terminal_receipts_observed": len(terminal_paths),
        },
        "terminal_receipts": {
            "status": "missing" if blocked else "complete",
            "required_count": len(rows),
            "observed_count": len(terminal_paths),
            "missing_count": len(rows) - len(terminal_paths),
            "paths": terminal_paths,
        },
        "scheduler": {"existing_processes_killed": 0, "existing_processes_restarted": 0},
        "side_effects": {
            "processes_stopped": 0,
            "processes_restarted": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "plan_writes": 0,
        },
        **_zero_credit(),
    }
    return value


def _write_pair(reports: Path, batch_id: str, payload: dict[str, object], *, markdown: bool = True) -> tuple[Path, Path | None]:
    json_path = reports / f"{audit.REPORT_PREFIX}{batch_id}.json"
    md_path = reports / f"{audit.REPORT_PREFIX}{batch_id}.zh-CN.md"
    _write_json(json_path, payload)
    if markdown:
        md_path.write_text(
            f"# F3 MLP hidden16 current-manifest diagnostic batch\n\n- batch=`{batch_id}`\n- diagnostic_only=true; credit=`0`\n",
            encoding="utf-8",
        )
        return json_path, md_path
    return json_path, None


def _full_fixture(tmp_path: Path) -> Path:
    reports = tmp_path / "reports"
    reports.mkdir()
    for batch_index, seed in enumerate(audit.SEEDS):
        for chunk_index in range(4):
            start = chunk_index * 8
            rows = [(audit.EXPECTED_CASE_IDS[index], seed) for index in range(start, start + 8)]
            batch_id = f"seed{seed}-chunk{chunk_index}"
            _write_pair(reports, batch_id, _batch_report(batch_id, rows))
    return reports


def test_complete_fixed_96_pair_rollup_never_opens_embedded_artifacts(tmp_path: Path) -> None:
    reports = _full_fixture(tmp_path)
    result = audit.build_audit(reports)

    assert result["status"] == "complete_diagnostic_rollup"
    assert result["coverage"]["expected_case_seed_count"] == 96
    assert result["coverage"]["unique_planned_case_seed_pairs"] == 96
    assert result["coverage"]["unique_result_case_seed_pairs"] == 96
    assert result["coverage"]["fully_auditable_diagnostic_rows"] == 96
    assert result["coverage"]["row_failures"] == 0
    assert result["input_boundary"]["hdf5_opened"] is False
    assert result["input_boundary"]["checkpoint_opened"] is False
    assert result["credit"] == 0
    audit.validate_audit_report(result)


def test_missing_markdown_and_duplicate_case_seed_are_reported(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    rows = [(audit.EXPECTED_CASE_IDS[0], 17), (audit.EXPECTED_CASE_IDS[1], 17)]
    first = _batch_report("duplicate-a", rows, blocked=True)
    _write_pair(reports, "duplicate-a", first, markdown=False)
    second = _batch_report("duplicate-b", rows, blocked=True)
    _write_pair(reports, "duplicate-b", second)

    result = audit.build_audit(reports)
    codes = {item["code"] for item in result["issues"]}
    assert result["status"] == "incomplete_diagnostic_rollup"
    assert "duplicate_case_seed_pair" in codes
    assert result["coverage"]["duplicate_planned_case_seed_pairs"]
    assert result["coverage"]["missing_planned_case_seed_pairs"]
    assert result["coverage"]["json_markdown_pair_failures"] >= 1


def test_blocked_missing_receipts_stay_zero_credit_and_never_become_auditable(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    case_id = audit.EXPECTED_CASE_IDS[0]
    payload = _batch_report("blocked-zero", [(case_id, 17)], blocked=True)
    _write_pair(reports, "blocked-zero", payload)

    result = audit.build_audit(reports)
    row = result["row_audits"][0]
    assert row["checks"]["process_receipt_present"] is False
    assert row["checks"]["terminal_receipt_present"] is False
    assert row["checks"]["missing_receipts_remain_zero_credit"] is True
    assert row["fully_auditable_diagnostic_row"] is False
    assert row["credit_assigned"] == 0
    assert result["credit"] == 0


def test_positive_credit_with_missing_receipt_is_flagged_closed(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    case_id = audit.EXPECTED_CASE_IDS[0]
    payload = _batch_report("blocked-positive", [(case_id, 17)], blocked=True, positive_credit=True)
    _write_pair(reports, "blocked-positive", payload)

    result = audit.build_audit(reports)
    row = result["row_audits"][0]
    assert result["status"] == "incomplete_diagnostic_rollup"
    assert row["checks"]["diagnostic_zero_credit"] is False
    assert any(item.get("issue_code") == "positive_or_drifted_credit" for item in result["issues"])


def test_non_runner_validation_summary_is_ignored_and_verify_cli_is_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    batch_id = "nonrunner-boundary"
    _write_pair(reports, batch_id, _batch_report(batch_id, [(audit.EXPECTED_CASE_IDS[0], 17)]))
    validation_json = reports / f"{audit.REPORT_PREFIX}VALIDATION.json"
    validation_md = reports / f"{audit.REPORT_PREFIX}VALIDATION.zh-CN.md"
    _write_json(validation_json, {"schema": "core.f3.mlp.hidden16.current_manifest.diagnostic_batch.validation_summary.v1"})
    validation_md.write_text("validation summary\n", encoding="utf-8")

    output = tmp_path / "rollup.json"
    markdown = tmp_path / "rollup.md"
    assert audit.main(["--reports-dir", str(reports), "--output", str(output), "--markdown-output", str(markdown)]) == 1
    captured = json.loads(capsys.readouterr().out)
    assert captured["status"] == "incomplete_diagnostic_rollup"
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["ignored_non_runner_json"][0]["schema"].endswith("validation_summary.v1")

    assert audit.main(["--verify-report", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "verified"
    assert "Boundary" in markdown.read_text(encoding="utf-8")
